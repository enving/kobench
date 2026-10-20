"""Die Harnesses: sechs Wege, Firmendaten an ein Sprachmodell anzubinden, alle mit demselben Antwortmodell.

Jedes Harness hat `antworte(frage, nutzer=None) -> dict` mit:
  antwort   Text (deutsch, mit [quell-id]-Zitaten)
  kontext   IDs der Dokumente, die das Modell zu sehen bekam
  schritte  Protokoll (Suchanfragen, Werkzeugaufrufe) für Bericht und Nachvollzug
  tokens    {"rein": n, "raus": n}

`nutzer` ist ein Name aus `rechte.yaml` des Datensatzes (bei Fragen mit `nutzer`). Harnesses ohne
Rechte-Unterstützung ignorieren ihn; ob sie dabei fremde Dokumente in den Kontext holen, misst die
Leck-Quote im Bericht. Ein eigenes Harness: Klasse unten anlegen und in `ALLE` eintragen (docs/eigenes-harness.md).
"""
import hashlib
import json
import os
import re
import time
from functools import lru_cache

from . import llm
from .korpus import Index, als_kontext, dokumente, firma, nach_id


def system_prompt():
    f = firma()
    return f"""Du bist der interne Wissensassistent von {f['name']}. Heute ist der {f['stichtag']}.
Beantworte die Frage auf Deutsch, knapp und vollständig, nur auf Grundlage der bereitgestellten Firmendaten.
Belege jede Aussage mit der Quell-ID in eckigen Klammern, z. B. [salesforce:deal-3].
Fehlt eine Information in den Daten, sag das klar und erfinde nichts.
Widersprechen sich Quellen (z. B. Kopien eines Dokuments), benenne den Widerspruch und welche Quelle maßgeblich ist."""


def _antwort(frage, kontext_text, kontext_ids, schritte=None, bloecke=None):
    """Der gemeinsame letzte Schritt: gleicher Systemprompt, gleiches Modell, nur der Kontext unterscheidet sich."""
    nutzer = f"Firmendaten:\n{kontext_text}\n\nFrage: {frage}" if kontext_text else f"Frage: {frage}"
    msg, usage = llm.chat([{"role": "system", "content": system_prompt()}, {"role": "user", "content": nutzer}])
    return {"antwort": msg["content"], "kontext": kontext_ids, "schritte": schritte or [],
            "bloecke": len(kontext_ids) if bloecke is None else bloecke,
            "tokens": {"rein": usage.get("prompt_tokens", 0), "raus": usage.get("completion_tokens", 0)}}


class Harness:
    name = ""
    titel = ""
    beschreibung = ""

    def antworte(self, frage, nutzer=None):
        raise NotImplementedError


# --------------------------------------------------------------------------- 1. Ohne Kontext

class OhneKontext(Harness):
    name = "ohne"
    titel = "Ohne Kontext"
    beschreibung = "Nur das Sprachmodell, keine Firmendaten. Untergrenze: zeigt, was das Modell rät."

    def antworte(self, frage, nutzer=None):
        return _antwort(frage, "", [])


# --------------------------------------------------------------------------- 2. Klassisches RAG

class BM25(Harness):
    name = "bm25"
    titel = "Klassisches RAG (BM25)"
    beschreibung = "Stichwortsuche über alle Dokumente, die 8 besten gehen ins Modell."

    @lru_cache
    def index(self):
        return Index(dokumente())

    def antworte(self, frage, nutzer=None):
        treffer = self.index().bm25_suche(frage, 8)
        return _antwort(frage, als_kontext(treffer), [d["id"] for d in treffer],
                        [{"suche": frage, "treffer": [d["id"] for d in treffer]}])


# --------------------------------------------------------------------------- 3. Hybrid-RAG

class Hybrid(Harness):
    name = "hybrid"
    titel = "Hybrid-RAG (BM25 + Embeddings)"
    beschreibung = "Stichwort- und Bedeutungssuche, per Rangfusion vereint, die 8 besten gehen ins Modell."

    @lru_cache
    def index(self):
        return Index(dokumente(), dense=True)

    def antworte(self, frage, nutzer=None):
        treffer = self.index().hybrid_suche(frage, 8)
        return _antwort(frage, als_kontext(treffer), [d["id"] for d in treffer],
                        [{"suche": frage, "treffer": [d["id"] for d in treffer]}])


# --------------------------------------------------------------------------- 4. Kundenakte
#
# Setzt CRM-Dokumente im Format von daten/beispiel/erzeugen.py voraus: Accounts `salesforce:acct-…` mit Titel
# „CRM-Account <Name>“, Deals `salesforce:deal-…` mit Zeilen „Account: <Name> (acct-…)“, „Stage:“,
# „Betrag: 12.345 USD“, „Close-Datum:“. Eigene Daten in anderem Format: _deals() und entitaetskarten()
# anpassen. Ohne Accounts verhält sich die Kundenakte wie Hybrid-RAG plus leere Pipeline-Übersicht.

_KOPIE = re.compile(r"copy|kopie|WIP|entwurf|draft|internal_only|shared_v2|\(\d+\)|\(v\d\)| - KM$|- old$", re.I)


def _deals(docs):
    deals = []
    for d in docs:
        if not d["id"].startswith("salesforce:deal-"):
            continue
        f = dict(z.split(": ", 1) for z in d["text"].splitlines()[1:] if ": " in z)
        f["id"], f["name"] = d["id"], d["titel"].removeprefix("CRM-Deal ")
        try:
            f["betrag"] = float(f.get("Betrag", "0").split()[0].replace(".", "").replace(",", "."))
        except ValueError:
            f["betrag"] = 0.0
        f.setdefault("Stage", "?")
        f.setdefault("Close-Datum", "")
        deals.append(f)
    return deals


@lru_cache
def entitaetskarten():
    """Vorberechnete Steckbriefe je Kunde und eine Pipeline-Übersicht, rein aus den Daten abgeleitet.

    Verknüpfungen (Kunde -> Deals, Tickets, Seiten, Kanal) und Summen werden einmal beim Einlesen
    gebaut statt bei jeder Frage neu zusammengesucht. Jede Zeile trägt die ID des Ursprungsdokuments.
    """
    docs = dokumente()
    alle_deals = _deals(docs)
    karten = []
    for a in (d for d in docs if d["id"].startswith("salesforce:acct-")):
        name = a["titel"].removeprefix("CRM-Account ")
        acc = a["id"].split(":", 1)[1]
        zeilen = a["text"].splitlines()
        z = [f"KUNDENSTECKBRIEF {name} ({acc})", f"Stammdaten: {'; '.join(zeilen[1:4])} [{a['id']}]"]
        kanal = nach_id().get(f"slack:{acc}")
        if kanal:
            z.append(f"Slack-Kanal: {'; '.join(kanal['text'].splitlines()[:3])} [{kanal['id']}]")
        deals = [x for x in alle_deals if f"({acc})" in x.get("Account", "")]
        offen = [x for x in deals if not x["Stage"].startswith("Closed")]
        zu = [x for x in deals if x["Stage"].startswith("Closed")]
        if deals:
            z.append(f"Deals: {len(offen)} offen ({sum(x['betrag'] for x in offen):,.0f} USD), "
                     f"{len(zu)} entschieden ({sum(1 for x in zu if x['Stage'] == 'Closed Won')} gewonnen)"
                     .replace(",", "."))
            for x in sorted(deals, key=lambda x: x["Close-Datum"]):
                z.append(f"- {x['name']}: {x['Stage']}, {x.get('Betrag', '?')}, Close {x['Close-Datum']}"
                         + (f", Wahrscheinlichkeit {x['Wahrscheinlichkeit']}" if "Wahrscheinlichkeit" in x else "")
                         + (f", nächster Schritt: {x['Nächster Schritt']}" if "Nächster Schritt" in x else "")
                         + f" [{x['id']}]")
        tickets = [d for d in docs if d["system"] == "jira" and name in d["text"]]
        if tickets:
            z.append("Tickets (Jira), neueste zuerst:")
            for t in sorted(tickets, key=lambda t: t.get("datum") or "", reverse=True):
                status = next((l for l in t["text"].splitlines() if l.startswith("Status:")), "Status: ?")
                z.append(f"- {t.get('datum')} {t['titel'].removeprefix('Jira ')} | {status} [{t['id']}]")
        seiten = [d for d in docs if d["system"] == "wiki" and name.lower() in d["titel"].lower()]
        if seiten:
            z.append("Wiki-Seiten (neueste zuerst; Kopien und Entwürfe markiert):")
            for s in sorted(seiten, key=lambda s: s.get("datum") or "", reverse=True):
                marke = " [KOPIE/ENTWURF - nicht maßgeblich]" if _KOPIE.search(s["titel"]) else ""
                z.append(f"- {s.get('datum')} {s['titel'].removeprefix('Confluence: ')}{marke} [{s['id']}]")
        if len(z) > 3:
            karten.append({"id": f"karte:{acc}", "system": "kundenakte", "titel": f"Steckbrief {name}",
                           "datum": None, "text": "\n".join(z)})
    offen = sorted((x for x in alle_deals if not x["Stage"].startswith("Closed")), key=lambda x: -x["betrag"])
    karten.append({"id": "karte:pipeline", "system": "kundenakte", "titel": "Pipeline-Übersicht offene Deals",
                   "datum": None, "text": "PIPELINE-ÜBERSICHT: alle offenen Opportunities, nach Betrag sortiert\n"
                   + "\n".join(f"{i + 1}. {x['name']}: {x.get('Betrag', '?')}, {x['Stage']}, Close {x['Close-Datum']} "
                               f"[{x['id']}]" for i, x in enumerate(offen))})
    return karten


@lru_cache
def alias_index():
    """Namen und Schlüssel -> Steckbrief, z. B. 'Corvid', 'acct-2', 'deal-3', 'TW-101' -> Steckbrief."""
    aliase = {}
    for k in entitaetskarten():
        if k["id"] == "karte:pipeline":
            continue
        name = k["titel"].removeprefix("Steckbrief ")
        aliase[name.lower()] = k["id"]
        erstes = name.split()[0].lower()
        if len(erstes) >= 5 and erstes not in ("health", "medical", "group", "systems", "global"):
            aliase.setdefault(erstes, k["id"])
        for schluessel in re.findall(r"\[(?:salesforce|jira|slack):([^\]]+)\]", k["text"]):
            aliase.setdefault(schluessel.lower(), k["id"])
    return aliase


class Kundenakte(Harness):
    name = "kundenakte"
    titel = "Kundenakte (Steckbriefe + Entitäten + Hybrid-RAG)"
    beschreibung = ("Beim Einlesen werden Kunden-Steckbriefe und eine Pipeline-Übersicht gebaut "
                    "(Verknüpfungen, Summen, Kopien markiert). Namen und Schlüssel in der Frage "
                    "werden auf Steckbriefe aufgelöst; dazu Hybrid-Suche über die Dokumente.")

    @lru_cache
    def index(self):
        return Index(dokumente(), dense=True)

    def antworte(self, frage, nutzer=None):
        karten = {k["id"]: k for k in entitaetskarten()}
        text = frage.lower()
        verknuepft = list(dict.fromkeys(kid for alias, kid in alias_index().items()
                                        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)))[:2]
        auswahl = [karten[k] for k in verknuepft] + [karten["karte:pipeline"]]
        # Verweise aus den Steckbriefen auflösen: die passendsten verknüpften Seiten und Tickets im Volltext.
        verweise = {i for k in verknuepft for i in re.findall(r"\[((?:confluence|jira):[^\]]+)\]", karten[k]["text"])}
        if verweise:
            unter = Index([nach_id()[i] for i in sorted(verweise)], dense=True)
            auswahl += unter.hybrid_suche(frage, 2)
        treffer = [d for d in self.index().hybrid_suche(frage, 12) if d not in auswahl][:6]
        auswahl += treffer
        # Was in einem Steckbrief steht, hatte das Modell im Kontext (Zeile mit ID).
        ids = [d["id"] for d in auswahl]
        for k in auswahl[:len(verknuepft) + 1]:
            ids += [i for i in re.findall(r"\[([a-z]+:[^\]]+)\]", k["text"]) if i in nach_id()]
        hinweis = ("Steckbriefe (karte:...) sind von der Kundenakte aus den Daten verdichtet; "
                   "zitiere die IDs am Zeilenende.\n\n")
        return _antwort(frage, hinweis + als_kontext(auswahl, 9000), list(dict.fromkeys(ids)),
                        [{"entitaeten": verknuepft}, {"suche": frage, "treffer": [d["id"] for d in treffer]}],
                        bloecke=len(auswahl))


# --------------------------------------------------------------------------- 5. Agent

WERKZEUGE = [
    {"type": "function", "function": {
        "name": "suche", "description": "Durchsucht alle Firmendaten (CRM, Tickets, Wiki, Chat, Ablage). "
        "Liefert IDs, Titel und Anfang des Textes. Sind die Daten englisch, finden englische Suchbegriffe mehr.",
        "parameters": {"type": "object", "properties": {"anfrage": {"type": "string"}}, "required": ["anfrage"]}}},
    {"type": "function", "function": {
        "name": "lies", "description": "Liest ein Dokument vollständig anhand seiner ID.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
]


class Agent(Harness):
    name = "agent"
    titel = "Agent mit Suchwerkzeug"
    beschreibung = "Das Modell sucht selbst: mehrere Suchanfragen und Dokumente lesen, bis zu 8 Runden."

    @lru_cache
    def index(self):
        return Index(dokumente(), dense=True)

    def antworte(self, frage, nutzer=None, runden=8):
        verlauf = [{"role": "system", "content": system_prompt() + "\nNutze die Werkzeuge, bevor du antwortest. "
                    "Suche mehrfach mit verschiedenen (auch englischen) Begriffen, wenn nötig."},
                   {"role": "user", "content": f"Frage: {frage}"}]
        gesehen, schritte, rein, raus = [], [], 0, 0
        for _ in range(runden):
            msg, usage = llm.chat(verlauf, werkzeuge=WERKZEUGE)
            rein += usage.get("prompt_tokens", 0)
            raus += usage.get("completion_tokens", 0)
            aufrufe = msg.get("tool_calls") or []
            verlauf.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls", "_roh")})
            if not aufrufe:
                return {"antwort": msg["content"], "kontext": gesehen, "schritte": schritte, "bloecke": len(gesehen),
                        "tokens": {"rein": rein, "raus": raus}}
            for a in aufrufe:
                try:
                    argumente = json.loads(a["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    argumente = {}
                if a["function"]["name"] == "suche":
                    treffer = self.index().hybrid_suche(argumente.get("anfrage", ""), 8)
                    ergebnis = "\n".join(f"[{d['id']}] {d['titel']}: {d['text'][:200]}" for d in treffer)
                    gesehen += [d["id"] for d in treffer if d["id"] not in gesehen]
                    schritte.append({"suche": argumente.get("anfrage"), "treffer": [d["id"] for d in treffer]})
                else:
                    d = nach_id().get(argumente.get("id", ""))
                    ergebnis = f"[{d['id']}] {d['titel']}\n{d['text']}" if d else "Kein Dokument mit dieser ID."
                    if d and d["id"] not in gesehen:
                        gesehen.append(d["id"])
                    schritte.append({"lies": argumente.get("id")})
                verlauf.append({"role": "tool", "name": a["function"]["name"], "content": ergebnis,
                                "tool_call_id": a["id"]})
        verlauf.append({"role": "user", "content": "Antworte jetzt mit dem, was du gefunden hast."})
        msg, usage = llm.chat(verlauf)
        return {"antwort": msg["content"], "kontext": gesehen, "schritte": schritte, "bloecke": len(gesehen),
                "tokens": {"rein": rein + usage.get("prompt_tokens", 0), "raus": raus + usage.get("completion_tokens", 0)}}


# --------------------------------------------------------------------------- 6. Alles im Kontext

# Zeichenbudget für den Volltext. 330.000 Zeichen sind bei ~2,1 Zeichen je Token etwa 157.000 Tokens und passen in
# ein Fenster von 200.000 Tokens. Für kleinere Fenster (z. B. lokale Modelle) KOBENCH_VOLLTEXT_ZEICHEN senken.
VOLLTEXT_ZEICHEN = int(os.environ.get("KOBENCH_VOLLTEXT_ZEICHEN", 330_000))


def _volltext_auswahl(docs, budget=None):
    """Was ins Fenster passt: Dokumente in fester Reihenfolge nach sha256("volltext:" + ID), bis das Budget voll
    ist; ausgegeben in Korpus-Reihenfolge. Passt alles, ist das der ganze Korpus."""
    budget = VOLLTEXT_ZEICHEN if budget is None else budget
    stuecke = {d["id"]: len(als_kontext([d], 100000)) + 2 for d in docs}
    if sum(stuecke.values()) <= budget:
        return list(docs)
    drin, summe = set(), 0
    for i in sorted(stuecke, key=lambda i: hashlib.sha256(f"volltext:{i}".encode()).hexdigest()):
        if summe + stuecke[i] > budget:
            continue
        drin.add(i)
        summe += stuecke[i]
    return [d for d in docs if d["id"] in drin]


class Volltext(Harness):
    name = "volltext"
    titel = "Alles im Kontext (Obergrenze)"
    beschreibung = ("Der ganze Korpus geht bei jeder Frage ins Modell, so viel ins Kontextfenster passt. "
                    "Teuer, aber ohne Suchfehler, solange alles passt.")

    @lru_cache
    def auswahl(self):
        return _volltext_auswahl(dokumente())

    def antworte(self, frage, nutzer=None):
        docs = self.auswahl()
        alle = len(dokumente())
        schritte = [] if len(docs) == alle else [{"volltext_gekuerzt": {"dokumente": len(docs), "von": alle,
                                                                      "budget_zeichen": VOLLTEXT_ZEICHEN}}]
        return _antwort(frage, als_kontext(docs, 100000), [d["id"] for d in docs], schritte)


# --------------------------------------------------------------------------- Register

ALLE = {h.name: h for h in (OhneKontext(), BM25(), Hybrid(), Kundenakte(), Agent(), Volltext())}


def registrieren(harness):
    """Ein eigenes Harness (Objekt mit `name`, `titel`, `beschreibung`, `antworte(frage, nutzer=None)`) eintragen.
    Bibliotheken von Anbietern rufen das beim Import auf oder liefern eine Liste `HARNESSES` (docs/eigenes-harness.md)."""
    for attr in ("name", "titel", "beschreibung"):
        if not getattr(harness, attr, ""):
            raise ValueError(f"Harness ohne {attr}")
    if not callable(getattr(harness, "antworte", None)):
        raise ValueError(f"Harness {harness.name!r} ohne antworte(frage, nutzer=None)")
    if harness.name in ALLE and ALLE[harness.name] is not harness:
        raise ValueError(f"Harness-Name {harness.name!r} ist schon vergeben")
    ALLE[harness.name] = harness
    return harness


def modul_laden(name):
    """Python-Modul importieren und dessen Harnesses registrieren (`HARNESSES` = Liste von Objekten)."""
    import importlib
    modul = importlib.import_module(name)
    for h in getattr(modul, "HARNESSES", []):
        registrieren(h)
    return modul


def zeitmessung(harness, frage, nutzer=None):
    t = time.time()
    erg = harness.antworte(frage, nutzer=nutzer)
    erg["sekunden"] = round(time.time() - t, 2)
    return erg
