"""Benchmark-Lauf: Harnesses x Fragen -> ergebnisse/<lauf>/ (Antworten, Bewertung, Bericht).

  uv run kobench                         # alle Harnesses, alle Fragen
  uv run kobench -H bm25,agent -f q01,q10
  uv run kobench -k fragen-test.yaml     # zweiter, geheimer Fragensatz (eigener Lauf, eigener Bericht)
  uv run kobench --bericht ergebnisse/2026-10-16-1530   # nur Bericht neu schreiben
"""
import argparse
import datetime as dt
import json
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import llm
from .bewertung import bewerte, leck_metriken
from .harnesses import ALLE, modul_laden, zeitmessung
from .korpus import DATEN, KORPUS, WURZEL, dokumente, fragen, katalog_pfad

TYPEN = ["fakt", "liste", "multihop", "zeit", "version", "nadel", "unbeantwortbar", "rechnen", "rechte"]


def commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=WURZEL,
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return "?"


def bearbeite(n, f):
    """Eine Frage an ein Harness und an den Richter. Das Harness bekommt nur Fragetext und Nutzer;
    der Richter nur die Felder aus bewertung.FUER_RICHTER (nie `hintergrund`)."""
    erg = zeitmessung(ALLE[n], f["frage"], nutzer=f.get("nutzer"))
    urteil = bewerte(f, erg)
    return {"harness": n, "frage": f["id"], "typ": f["typ"], "nutzer": f.get("nutzer"), **erg, "bewertung": urteil}


def laufe(harness_namen, frage_ids, ziel, parallel, katalog=None):
    alle_fragen = [f for f in fragen(katalog) if not frage_ids or f["id"] in frage_ids]
    ziel.mkdir(parents=True, exist_ok=True)
    datei = ziel / "ergebnisse.jsonl"
    fertig = set()
    if datei.exists():  # Fortsetzen nach Abbruch
        fertig = {(e["harness"], e["frage"]) for e in map(json.loads, datei.read_text().splitlines())}
    for n in harness_namen:  # Indizes vorab bauen (Embeddings), nicht in jedem Thread
        if hasattr(ALLE[n], "index"):
            ALLE[n].index()
    auftraege = [(n, f) for n in harness_namen for f in alle_fragen if (n, f["id"]) not in fertig]
    print(f"{len(auftraege)} Läufe ({len(fertig)} schon fertig) -> {ziel}")

    with ThreadPoolExecutor(parallel) as pool, datei.open("a") as fh:
        zukunft = {pool.submit(bearbeite, n, f): (n, f["id"]) for n, f in auftraege}
        for z in as_completed(zukunft):
            n, fid = zukunft[z]
            try:
                e = z.result()
            except Exception as fehler:  # noqa: BLE001 - ein Fehler soll den Lauf nicht stoppen
                print(f"  FEHLER {n} {fid}: {fehler}")
                continue
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            fh.flush()
            b = e["bewertung"]
            leck = f"  leck {len(b['leck_verboten'])}/{len(b['leck_streng'])}" if "leck_streng" in b else ""
            print(f"  {n:13} {fid}  score {b['score']:.2f}  erfunden {'JA ' if b['erfunden'] else 'nein'}"
                  f"  gefunden {b['gefunden']}{leck}  {e['sekunden']:.1f}s")


def bericht(ziel):
    eintraege = [json.loads(z) for z in (ziel / "ergebnisse.jsonl").read_text().splitlines()]
    meta = json.loads((ziel / "lauf.json").read_text())
    katalog = meta.get("katalog")
    fr = {f["id"]: f for f in fragen(katalog)}
    typen = [t for t in TYPEN if any(f["typ"] == t for f in fr.values())]
    nach_h = defaultdict(list)
    for e in eintraege:
        nach_h[e["harness"]].append(e)
    reihen = [h for h in ALLE if h in nach_h]

    def mittel(werte):
        werte = [w for w in werte if w is not None]
        return sum(werte) / len(werte) if werte else None

    anzahl = f"{meta.get('dokumente', len(dokumente())):,}".replace(",", ".")
    z = [f"# Benchmark-Lauf {ziel.name}", "",
         f"Datensatz: {meta.get('datensatz', '?')}, {anzahl} Dokumente. "
         f"Fragenkatalog: {katalog or 'fragen.yaml'} ({len(fr)} Fragen). Antwortmodell `{meta['antwortmodell']}` für alle Harnesses, "
         f"Richter `{meta['richter']}`, Seed {llm.SEED}, Commit `{meta['commit']}`.", "",
         "## Gesamt", "",
         "| Harness | Antwortqualität | Erfunden | Quellen gefunden | Quellen zitiert | Tokens/Frage | Sekunden/Frage |",
         "|---|---|---|---|---|---|---|"]
    for h in reihen:
        e = nach_h[h]
        z.append(f"| {ALLE[h].titel} | {mittel([x['bewertung']['score'] for x in e]):.0%} "
                 f"| {sum(x['bewertung']['erfunden'] for x in e)}/{len(e)} "
                 f"| {mittel([x['bewertung']['gefunden'] for x in e]) or 0:.0%} "
                 f"| {mittel([x['bewertung']['zitiert'] for x in e]) or 0:.0%} "
                 f"| {mittel([x['tokens']['rein'] + x['tokens']['raus'] for x in e]):,.0f} "
                 f"| {mittel([x['sekunden'] for x in e]):.1f} |".replace(",", "."))
    z += ["", "Antwortqualität = Anteil erfüllter Prüfpunkte (LLM-Richter). Erfunden = Antworten mit "
          "unbelegter Tatsachenbehauptung. Quellen gefunden = Anteil der Gold-Quellen, die das Modell "
          "im Kontext hatte (Volltext: immer 100 %).", "", "## Nach Fragetyp (Antwortqualität)", "",
          "| Harness | " + " | ".join(typen) + " |", "|---" * (len(typen) + 1) + "|"]
    for h in reihen:
        zellen = []
        for t in typen:
            m = mittel([x["bewertung"]["score"] for x in nach_h[h] if x["typ"] == t])
            zellen.append("–" if m is None else f"{m:.0%}")
        z.append(f"| {ALLE[h].titel} | " + " | ".join(zellen) + " |")
    rechte_ids = [fid for fid, f in fr.items() if f.get("nutzer")]
    if rechte_ids:
        z += ["", "## Leck-Quote (Fragen mit Nutzer, deterministisch)", "",
              "| Harness | Rechte-Fragen | Leck (verboten) | Leck (streng) | fremde IDs im Kontext je Frage |",
              "|---|---|---|---|---|"]
        for h in reihen:
            lecks = [leck_metriken(fr[x["frage"]], x) for x in nach_h[h] if x["frage"] in rechte_ids]
            if not lecks:
                continue
            n = len(lecks)
            z.append(f"| {ALLE[h].titel} | {n} | {sum(bool(l['leck_verboten']) for l in lecks) / n:.0%} "
                     f"| {sum(bool(l['leck_streng']) for l in lecks) / n:.0%} "
                     f"| {mittel([len(l['leck_streng']) for l in lecks]):.1f} |")
        z += ["", "Leck (verboten) = Anteil der Rechte-Fragen, bei denen eine antworttragende fremde ID "
              "(`verboten` der Frage) im Kontext des Modells war. Leck (streng) = Anteil mit irgendeiner "
              "Kontext-ID, die `kobench.rechte.darf(nutzer, id)` verbietet (Steckbriefe `karte:` zählen über "
              "ihre Zeilen-IDs). Harnesses ohne Rechte-Unterstützung ignorieren den Nutzer."]
    z += ["", "## Je Frage (Antwortqualität, * = erfunden)", "",
          "| Frage | Typ | " + " | ".join(reihen) + " |", "|---" * (len(reihen) + 2) + "|"]
    for fid in sorted({e["frage"] for e in eintraege}):
        zellen = []
        for h in reihen:
            x = next((e for e in nach_h[h] if e["frage"] == fid), None)
            zellen.append("–" if not x else f"{x['bewertung']['score']:.0%}" + ("*" if x["bewertung"]["erfunden"] else ""))
        z.append(f"| {fid} {fr[fid]['frage'][:60]} | {fr[fid]['typ']} | " + " | ".join(zellen) + " |")
    z += ["", "## Harnesses", ""] + [f"- **{ALLE[h].titel}** (`{h}`): {ALLE[h].beschreibung}" for h in reihen]
    (ziel / "bericht.md").write_text("\n".join(z) + "\n")
    print(f"Bericht: {ziel / 'bericht.md'}")


def main():
    vor = argparse.ArgumentParser(add_help=False)
    vor.add_argument("-m", "--modul", default="")
    for m in filter(None, vor.parse_known_args()[0].modul.split(",")):  # Plug-ins vor der Harness-Liste laden
        modul_laden(m)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-H", "--harness", default=",".join(ALLE), help="Komma-Liste, Standard: alle")
    p.add_argument("-f", "--fragen", default="", help="Komma-Liste von Frage-IDs, Standard: alle")
    p.add_argument("-k", "--katalog", default="fragen",
                   help="Fragenkatalog: Standard fragen.yaml des Datensatzes, sonst Dateiname im Datensatz-Ordner oder Pfad")
    p.add_argument("-m", "--modul", default="", help="Python-Modul(e) mit eigenen Harnesses (Liste HARNESSES), Komma-getrennt")
    p.add_argument("-o", "--ziel", help="Lauf-Ordner (zum Fortsetzen)")
    p.add_argument("-p", "--parallel", type=int, default=3)
    p.add_argument("--bericht", help="nur Bericht für diesen Lauf-Ordner schreiben")
    a = p.parse_args()
    if a.bericht:
        return bericht(Path(a.bericht))
    ziel = Path(a.ziel) if a.ziel else Path.cwd() / "ergebnisse" / dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    namen = [n for n in a.harness.split(",") if n]
    unbekannt = [n for n in namen if n not in ALLE]
    if unbekannt:
        p.error(f"unbekannte Harnesses: {unbekannt}; bekannt: {list(ALLE)}")
    ziel.mkdir(parents=True, exist_ok=True)
    alt = ziel / "lauf.json"
    korpus = KORPUS.name
    datensatz = DATEN.name
    if a.katalog:
        katalog_pfad(a.katalog)  # früh scheitern, wenn der Katalog fehlt
    if alt.exists() and json.loads(alt.read_text()).get("katalog") != a.katalog:
        p.error(f"{ziel} wurde mit einem anderen Katalog begonnen; -k passend setzen")
    if alt.exists() and json.loads(alt.read_text()).get("datensatz", datensatz) != datensatz:
        p.error(f"{ziel} wurde mit einem anderen Datensatz begonnen; KOBENCH_DATEN passend setzen")
    (ziel / "lauf.json").write_text(json.dumps({"antwortmodell": llm.ANTWORT_MODELL, "richter": llm.RICHTER_MODELL,
                                                "commit": commit(), "harnesses": namen, "katalog": a.katalog,
                                                "datensatz": datensatz, "korpus": korpus, "dokumente": len(dokumente()),
                                                "start": dt.datetime.now().isoformat(timespec="seconds")}, indent=1))
    laufe(namen, set(filter(None, a.fragen.split(","))), ziel, a.parallel, a.katalog)
    bericht(ziel)


if __name__ == "__main__":
    main()
