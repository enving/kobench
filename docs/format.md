# Datenformat

Ein Datensatz ist ein Ordner. Standard ist `daten/beispiel`; eigener Ordner über `KOBENCH_DATEN=<pfad>`.

## dokumente.jsonl

Ein Dokument je Zeile:

```json
{"id": "jira:TW-101", "system": "jira", "titel": "Jira TW-101: ...", "datum": "2026-10-06", "text": "..."}
```

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `id` | ja | `<system>:<schlüssel>`, eindeutig. Ist überall die Quellenangabe (Zitate der Antwort, Gold-Quellen, Rechte). |
| `system` | ja | z. B. `crm`, `jira`, `wiki`, `slack`, `sharepoint` |
| `titel` | ja | Anzeigetitel |
| `text` | ja | lesbarer Text mit allen relevanten Feldern |
| `datum` | nein | ISO-Datum oder `null` |

Ändern sich die IDs, müssen alle `quellen` in `fragen.yaml` neu geprüft werden (`uv run pytest` tut das für die Beispielfirma).

## fragen.yaml

```yaml
- id: q01
  typ: fakt            # fakt | liste | multihop | zeit | version | nadel | unbeantwortbar | rechnen | rechte
  frage: "Wie ist der Stand beim Ticket TW-101?"
  gold: "Musterantwort für Menschen und den Richter."
  punkte:              # Prüfpunkte, einzeln bewertet; bei unbeantwortbar: 1. Punkt "sagt klar, dass die Information fehlt"
    - Status In Progress
  quellen: [jira:TW-101]   # IDs, die eine vollständige Antwort braucht (für Quellen gefunden/zitiert)
  auch_ok: []              # weitere IDs, die als korrekte Quelle zählen (z. B. inhaltsgleiche Kopien)
  # nur für Rechte-Fragen:
  nutzer: gast             # Name aus rechte.yaml; das Harness bekommt ihn als `nutzer`
  verboten: [salesforce:deal-0]   # antworttragende Dokumente, die dieser Nutzer nicht sehen darf
  hintergrund: "..."       # Antwort mit vollen Rechten, nur zur Dokumentation; geht nie an Harness oder Richter
```

## firma.yaml (optional)

```yaml
name: Tidewell Software
stichtag: 15.10.2026   # "heute" im Systemprompt; hilft bei Zeitfragen
```

## rechte.yaml (optional, nur für Fragen mit `nutzer`)

Glob-Muster (fnmatch) auf die Dokument-ID; die **letzte** passende Regel gilt. Ein Nutzer sieht ein Dokument, wenn sich seine
Kreise mit denen des Dokuments überschneiden.

```yaml
kreise:  {alle: "Firmenöffentlich", vertrieb: "CRM, Angebote"}
quellen: [{muster: "salesforce:*", kreise: [vertrieb]}]
nutzer:  {gast: [alle]}
```

Keine Auffangregel `*` verwenden: jede ID soll bewusst zugeordnet sein (`tests/test_beispiel.py` prüft das für die Beispielfirma).

## Mehrere Fragensätze

`-k <datei>` wählt eine andere Fragendatei (Pfad oder Name im Datensatz-Ordner). Ein geheimer Testsatz gehört nicht ins
öffentliche Repo, sondern lokal neben die Daten.
