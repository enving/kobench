# kobench

Ein kleiner, ehrlicher Benchmark: Wie gut beantwortet eine KI Fragen zu den Daten einer Firma, je nachdem, **wie** man sie
an diese Daten anschließt? Er vergleicht sechs Anbindungen mit demselben Antwortmodell auf denselben Fragen und misst
Antwortqualität, Erfindungen, Quellen und ob Dokumente beim Modell landen, die der Fragende gar nicht sehen darf.

Gebaut für Folge 18 des Kanals Digitalalchemisten (Kontext-Benchmark). kobench ist **nur der Benchmark**: Er zeigt, wie man
misst und wie man ein eigenes Harness anschließt. Adapter für einzelne Anbieter gehören nicht hierher; sie leben in eigenen
Repos, die kobench als Abhängigkeit nutzen (siehe [docs/eigenes-harness.md](docs/eigenes-harness.md)).

## Schnellstart (ohne Era, ohne Registrierung)

Mitgeliefert ist eine frei erfundene Beispielfirma (Tidewell Software, 42 Dokumente, 13 Fragen mit belegten Musterantworten).

```bash
git clone https://github.com/enving/kobench && cd kobench
uv run pytest                 # Vertragstest mit Attrappen, kein API-Aufruf, kein Schlüssel
cp .env.example .env          # Anbieter und Schlüssel eintragen (oder ein lokales Modell, siehe unten)
uv run kobench -H ohne,bm25 -f q01,q04,q10     # kleiner Probelauf
uv run kobench                # alle Harnesses, alle Fragen
```

Ergebnis: `ergebnisse/<datum>/` mit `ergebnisse.jsonl` (jede Antwort, Kontext, Schritte, Tokens, Urteil), `lauf.json`
(Modelle, Datensatz) und `bericht.md`. Der Lauf setzt nach einem Abbruch fort (`-o <ordner>`); `--bericht <ordner>` schreibt
nur den Bericht neu.

Modelle (alles über Umgebungsvariablen, siehe `.env.example`):

| Anbieter (`KOBENCH_ANBIETER`) | Hinweis |
|---|---|
| `mistral` (Standard), `openai`, `anthropic` | je mit eigenem Schlüssel |
| `openai` mit `KOBENCH_BASE_URL` | jeder OpenAI-kompatible Server, auch lokal (Ollama, LM Studio, vLLM) |
| `claude-cli` | nutzt ein vorhandenes Claude-Code-Abo statt eines Schlüssels |

Der Richter kann ein anderes Modell sein (`KOBENCH_RICHTER_*`). Die Harnesses `hybrid`, `kundenakte` und `agent` brauchen
zusätzlich einen Embedding-Endpunkt (`KOBENCH_EMBED_*`); `ohne`, `bm25` und `volltext` kommen ohne aus.
Kosten: Der Beispieldatensatz ist klein. Ein Lauf aller Harnesses liegt bei einigen Hundert Modellaufrufen; große Korpora
treiben vor allem `volltext` hoch (der ganze Korpus bei jeder Frage).

## Die sechs Harnesses

| Name | Idee |
|---|---|
| `ohne` | Nur das Sprachmodell, keine Firmendaten. Untergrenze. |
| `bm25` | Klassisches RAG: Stichwortsuche, die 8 besten Dokumente gehen ins Modell. |
| `hybrid` | Stichwort- plus Bedeutungssuche (Embeddings), per Rangfusion vereint. |
| `kundenakte` | Beim Einlesen werden Steckbriefe je Kunde und eine Pipeline-Übersicht aus den Daten gebaut (Verknüpfungen, Summen, Kopien markiert), dazu Hybrid-Suche. Ohne Ontologie. |
| `agent` | Das Modell sucht selbst, mehrere Anfragen, Dokumente lesen, bis zu 8 Runden. |
| `volltext` | Der ganze Korpus im Kontext, so viel ins Fenster passt (`KOBENCH_VOLLTEXT_ZEICHEN`). Obergrenze, teuer. |

Alle benutzen denselben Systemprompt und dasselbe Antwortmodell (`harnesses._antwort`). Nur der Kontext unterscheidet sie.
Die `kundenakte` setzt CRM-, Ticket- und Wiki-Dokumente im Format der Beispielfirma voraus (siehe Grenzen).

## Eigenes Harness anschließen

Eine Klasse mit `antworte(frage, nutzer=None)`, die ein Dict mit `antwort`, `kontext`, `schritte` und `tokens` liefert:

```python
from kobench.harnesses import registrieren

class MeinSystem:
    name, titel, beschreibung = "mein", "Mein System", "Was es anders macht."
    def antworte(self, frage, nutzer=None):
        text, ids = ...  # dein System fragen
        return {"antwort": text, "kontext": ids, "schritte": [], "tokens": {"rein": 0, "raus": 0}}

HARNESSES = [MeinSystem()]   # in einem eigenen Paket; oder registrieren(MeinSystem())
```

```bash
uv run kobench -m mein_paket -H mein,bm25
```

Die Rückgabe, Rechte (`nutzer`), den Vertragstest und wie Anbieter-Adapter als eigene Repos aussehen sollten, steht in
[docs/eigenes-harness.md](docs/eigenes-harness.md).

## Eigenen Korpus und eigene Fragen anschließen

Ein Datensatz ist ein Ordner mit `dokumente.jsonl`, `fragen.yaml`, optional `firma.yaml` und `rechte.yaml`:

```bash
KOBENCH_DATEN=/pfad/zu/meiner-firma uv run kobench
```

Format der Dokumente, Fragen und Rechte: [docs/format.md](docs/format.md). Wie man einen Abzug aus dem Firmensimulator
**Era** (console.era.eon.io, Beta auf Einladung) einbindet: [docs/eigener-korpus.md](docs/eigener-korpus.md). Era-Daten sind
nicht im Repo.

Faustregeln für Fragen: erst am Korpus belegen (das Dokument lesen), dann eintragen; erfundene Musterantworten machen den
Benchmark wertlos. Halte einen zweiten Fragensatz **geheim** und miss dein Harness erst dort (`-k fragen-test.yaml`).
Wer ein Harness auf die sichtbaren Fragen hin verbessert, misst irgendwann nur noch Auswendiglernen.

## Metriken

| Spalte im Bericht | Bedeutung | Wie gemessen |
|---|---|---|
| Antwortqualität | Anteil erfüllter Prüfpunkte je Frage, gemittelt | LLM-Richter; sieht Frage, Musterantwort, Prüfpunkte, Belegdokumente |
| Erfunden | Antworten mit unbelegter oder falscher Tatsachenbehauptung | LLM-Richter |
| Quellen gefunden | Anteil der Gold-Quellen, die das Modell im Kontext hatte | deterministisch, ohne LLM |
| Quellen zitiert | Anteil der Gold-Quellen, die die Antwort als `[id]` nennt | deterministisch |
| Leck (verboten) | Rechte-Fragen, bei denen ein antworttragendes, verbotenes Dokument im Kontext war | deterministisch |
| Leck (streng) | Rechte-Fragen mit irgendeinem Kontext-Dokument, das `rechte.yaml` dem Nutzer verbietet | deterministisch |
| Tokens, Sekunden je Frage | Aufwand | aus der Antwort, gemessen |

Der Richter bekommt nie `hintergrund` (die Antwort mit vollen Rechten), `verboten` oder `nutzer`; der Vertragstest prüft das.
`unbeantwortbar`-Fragen belohnen ein klares „weiß ich nicht“, `version`-Fragen bestrafen veraltete Kopien.

## Grenzen

- Kleine Stichprobe: wenige Dutzend Fragen sagen nichts über deine Firma. Sie zeigen, wie man misst, nicht, wer gewinnt.
- Der Richter ist ein Sprachmodell und kann irren. Ein stärkeres Richtermodell als Antwortmodell ist besser; Stichproben
  per Hand prüfen. Ergebnisse zwischen verschiedenen Richtern sind nicht vergleichbar.
- Ein Lauf ist eine Messung, kein Beweis: Modelle sind nicht vollständig deterministisch (Seed wird gesetzt, wo der Anbieter es kann).
- Fragen sind deutsch, der Korpus englisch. Das ist gewollt (Hürde für reine Stichwortsuche); für deutsche Korpora anpassen.
- `kundenakte` und deren Entitätsauflösung sind auf das Datenformat der Beispielfirma zugeschnitten (CRM-Accounts und -Deals,
  Jira, Wiki, Slack). Bei anderen Daten `entitaetskarten()` anpassen, sonst verhält sie sich wie Hybrid-RAG.
- Die Rechte in `rechte.yaml` sind gesetzt, nicht gewachsen. Die Leck-Quote misst, was im Kontext des Modells landet, nicht
  was in der Antwort steht.
- Eine Harness-Wahl auf Basis einer Firma überträgt sich nicht automatisch auf eine andere.

## Lizenz

MIT, siehe `LICENSE`.
