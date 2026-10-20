# Eigenen Korpus anschließen

kobench liest `dokumente.jsonl` (Format: [format.md](format.md)). Woher die Dokumente kommen, ist deine Sache. Zwei Wege:

## 1. Eigene Firmendaten

Ein Skript, das je Datensatz (Deal, Konto, Ticket, Wiki-Seite, Chat-Kanal, Datei) ein Dokument schreibt, mit allen
relevanten Feldern als lesbarem Text und der ID `<system>:<schlüssel>`. Das Muster dafür ist
`daten/beispiel/erzeugen.py`. Achte auf Datenschutz: Kein Korpus mit echten Kundendaten in ein öffentliches Repo oder
an einen fremden Anbieter, den du nicht vorher geprüft hast.

Dann Fragen schreiben (am Korpus belegt), `rechte.yaml` falls du Rechte messen willst, und:

```bash
KOBENCH_DATEN=/pfad/zu/ordner uv run kobench
```

## 2. Abzug aus dem Firmensimulator Era

Era (https://console.era.eon.io, Beta auf Einladung; Ankündigung: https://www.eon.io/blog/era-build-and-test-ai-agents)
simuliert eine Firma: Salesforce, Slack, Jira/Confluence, SharePoint u. a. antworten mit der API des echten Produkts und
zusätzlich über MCP, nur lesend. Das Kontingent ist begrenzt; jeder REST- oder MCP-Aufruf zählt. Die Era-Daten sind
**nicht** Teil dieses Repos und dürfen nur mit eigenem Zugang geholt werden.

Vorgehen:

1. Mit eigenem Era-Zugang die Systeme einmal abziehen (Konsole/CLI/API von Era) und die Rohantworten lokal speichern.
   Jede Antwort roh aufheben, damit der Bau wiederholbar ist.
2. Ein Bauskript schreibt daraus `dokumente.jsonl`: je Datensatz ein Dokument, Felder als Text, ID `<system>:<schlüssel>`
   (`salesforce:deal-8`, `jira:TW-101`, `confluence:40103`, `slack:acct-0`, `sharepoint:<guid>`). HTML aus Confluence in
   Text umwandeln. Das Format der Felder, auf das `kundenakte` zählt, zeigt `daten/beispiel/erzeugen.py` (Zeilen
   `Account: <Name> (acct-N)`, `Stage:`, `Betrag: 12.345 USD`, `Close-Datum:`).
3. `firma.yaml` mit Name und Stichtag anlegen (Stichtag = Tag des Abzugs).
4. Fragen schreiben: erst das Dokument lesen, dann die Frage und die Musterantwort. Fragen auf Deutsch zu englischen
   Dokumenten sind eine bewusste Hürde.
5. `KOBENCH_DATEN=<ordner> uv run kobench`

Ändert sich das Bauskript, ändern sich eventuell die IDs. Dann alle `quellen` der Fragen neu prüfen.

Hinweis: Die Fragen und Daten aus der Folge werden nicht veröffentlicht, weil sie Inhalte der Era-Testfirma zitieren und der
Testsatz geheim bleiben muss, um nicht auswendig gelernt zu werden.
