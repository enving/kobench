"""Bewertung einer Antwort: Prüfpunkte per LLM-Richter, Quellen und Leck-Quote deterministisch."""
import json
import re

from . import llm
from .korpus import nach_id
from .rechte import darf

# Nur diese Felder einer Frage gehen an den Richter. `hintergrund` (Antwort mit vollen Rechten),
# `verboten` und `nutzer` bleiben draußen — der Richter soll die eingeschränkte Antwort bewerten.
FUER_RICHTER = ("id", "typ", "frage", "gold", "punkte", "quellen", "auch_ok")

RICHTER = """Du bewertest die Antwort eines Firmen-Wissensassistenten streng und fair.
Du bekommst: Frage, Musterantwort, Prüfpunkte, die Belegdokumente und die zu prüfende Antwort.
Für jeden Prüfpunkt: erfüllt=true nur, wenn die Antwort ihn inhaltlich korrekt enthält
(andere Formulierung, Sprache oder Zahlenformat ist egal). Ein Prüfpunkt der Form
"X nicht dabei" oder "keine falschen ..." ist erfüllt, wenn die Antwort den Fehler nicht macht.
erfunden=true, wenn die Antwort eine konkrete Tatsachenbehauptung enthält, die weder in der
Musterantwort noch in den Belegdokumenten steht und falsch oder unbelegt ist (Zahlen, Namen,
Daten, Status). Allgemeine Höflichkeit oder Rückfragen sind nicht erfunden.
Antworte nur mit JSON: {"punkte": [{"punkt": "...", "erfuellt": true}], "erfunden": false,
"begruendung": "ein bis zwei Sätze"}"""



def zitate(antwort):
    roh = []
    for gruppe in re.findall(r"\[([^\]]+)\]", antwort or ""):
        roh += [t.strip() for t in re.split(r"[,;]\s*", gruppe) if ":" in t]
    return list(dict.fromkeys(roh))


def quellen_metriken(frage, erg):
    gold, auch = set(frage["quellen"]), set(frage.get("auch_ok", []))
    kontext = set(erg["kontext"])
    zit = zitate(erg["antwort"])

    def recall(menge):
        if not gold:
            return None
        treffer = len(gold & menge)
        treffer += min(len(auch & menge), len(gold - menge))
        return round(treffer / len(gold), 3)

    return {"gefunden": recall(kontext), "zitiert": recall(set(zit)),
            "zitate": len(zit), "zitate_ungueltig": [z for z in zit if z not in nach_id() and not z.startswith("karte:")]}


def leck_metriken(frage, erg):
    """Leck-Prüfung für Fragen mit `nutzer` (deterministisch, ohne LLM). Sonst leer.

    verboten  Kontext-IDs aus der Liste `verboten` der Frage (antworttragende fremde Dokumente)
    streng    alle Kontext-IDs, die kobench.rechte.darf(nutzer, id) verbietet. Verdichtete
              Steckbriefe (karte:…) zählen nicht selbst; ihre Zeilen-IDs stehen ohnehin im Kontext.
    """
    nutzer = frage.get("nutzer")
    if not nutzer:
        return {}
    kontext = list(dict.fromkeys(erg["kontext"]))
    verboten = set(frage.get("verboten", []))
    return {"leck_verboten": [i for i in kontext if i in verboten],
            "leck_streng": [i for i in kontext if not i.startswith("karte:") and not darf(nutzer, i)]}


def bewerte(frage, erg):
    leck = leck_metriken(frage, erg)
    frage = {k: frage[k] for k in FUER_RICHTER if k in frage}
    # Gold-Quellen plus die von der Antwort zitierten Dokumente: korrekte Zusatzinfos aus
    # anderen Dokumenten sollen nicht als erfunden gelten.
    ids = list(dict.fromkeys(frage["quellen"] + frage.get("auch_ok", [])[:2] + zitate(erg["antwort"])[:8]))
    belege = "\n\n".join(f"[{q}] {nach_id()[q]['text'][:3000]}" for q in ids if q in nach_id())
    nutzer = (f"Frage: {frage['frage']}\n\nMusterantwort: {frage['gold']}\n\nPrüfpunkte:\n"
              + "\n".join(f"- {p}" for p in frage["punkte"])
              + f"\n\nBelegdokumente:\n{belege or '(keine, die Information gibt es nicht)'}"
              + f"\n\nZu prüfende Antwort:\n{erg['antwort']}")
    for versuch in range(3):  # der Richter liefert selten kaputtes JSON
        msg, _ = llm.chat([{"role": "system", "content": RICHTER}, {"role": "user", "content": nutzer}],
                          modell=llm.RICHTER_MODELL, json_modus=True)
        try:
            urteil = json.loads(msg["content"])
            break
        except json.JSONDecodeError:
            if versuch == 2:
                raise
    # Nur die vorgegebenen Prüfpunkte zählen; der Richter hängt manchmal eigene an.
    punkte = urteil.get("punkte", [])[:len(frage["punkte"])]
    erfuellt = sum(1 for p in punkte if p.get("erfuellt"))
    return {"punkte": punkte, "score": round(erfuellt / max(len(frage["punkte"]), 1), 3),
            "erfunden": bool(urteil.get("erfunden")), "begruendung": urteil.get("begruendung", ""),
            **quellen_metriken(frage, erg), **leck}
