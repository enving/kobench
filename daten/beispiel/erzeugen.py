"""Baut dokumente.jsonl der Beispielfirma Tidewell Software (frei erfunden, alle Namen und Zahlen ausgedacht).

    uv run python daten/beispiel/erzeugen.py

Die Dokumente sind so aufgebaut wie die Systeme einer echten Firma (CRM, Tickets, Wiki, Chat, Ablage),
damit alle sechs Harnesses laufen. Das Format der Felder steht in docs/format.md.
"""
import json
from pathlib import Path

ACCOUNTS = [  # (Name, Branche, Owner, Kanal-Zweck)
    ("Harbor Freight Logistics", "Logistics", "Ines Calloway", "route planning rollout and the enterprise renewal"),
    ("Maplewood Dental Group", "Healthcare", "Marek Voss", "appointment reminders and the mid-market renewal"),
    ("Corvid Analytics", "Software", "Priya Anand", "API integration and the expansion deal"),
    ("Northgate Brewing", "Food & Beverage", "Ines Calloway", "delivery scheduling for 40 pubs"),
    ("Silverline Credit Union", "Finance", "Marek Voss", "security review and contract renewal"),
    ("Aldermere Schools Trust", "Education", "Priya Anand", "pilot in 12 schools"),
]
# (id, Account-Nr, Titel-Zusatz, Stage, Betrag, Close, Wahrscheinlichkeit, Nächster Schritt)
DEALS = [
    (0, 0, "Renewal", "Negotiation", "184.000 USD", "2026-11-30", "70 %", "Preisrunde mit dem Einkauf am 04.11."),
    (1, 1, "Renewal", "Closed Won", "46.500 USD", "2026-09-18", "100 %", None),
    (2, 2, "Expansion", "Proposal", "92.300 USD", "2026-12-15", "50 %", "Angebot v2 an den CTO schicken"),
    (3, 3, "Pilot", "Closed Won", "28.000 USD", "2026-07-02", "100 %", None),
    (4, 4, "Renewal", "Prospecting", "131.750 USD", "2027-01-20", "20 %", "Security-Fragebogen beantworten"),
    (5, 5, "Pilot", "Qualification", "19.900 USD", "2026-11-12", "30 %", "Termin mit der Schulleitung"),
    (6, 3, "Expansion", "Closed Lost", "55.000 USD", "2026-08-14", "0 %", None),
]
JIRA = [  # (Key, Titel, Typ, Status, Prio, Bearbeiter, Melder, Datum, Kunde, Beschreibung)
    ("TW-101", "Route export fails for more than 500 stops", "Bug", "In Progress", "High", "Hana Okafor", "Dev Raman",
     "2026-10-06", "Harbor Freight Logistics",
     "Harbor Freight Logistics reports that exporting a route with more than 500 stops ends with a timeout. "
     "Workaround: split the route into two exports. Fix planned for release 4.8."),
    ("TW-102", "SMS reminders sent twice", "Bug", "Done", "Medium", "Tobias Lindgren", "Dev Raman",
     "2026-09-03", "Maplewood Dental Group",
     "Maplewood Dental Group patients received every reminder twice. Cause: duplicate cron entry after the 4.6 deploy. "
     "Removed in 4.6.2, resolved on 2026-09-05."),
    ("TW-103", "Rate limit for the public API too low", "Task", "To Do", "Medium", "Hana Okafor", "Priya Anand",
     "2026-10-09", "Corvid Analytics",
     "Corvid Analytics needs 600 requests per minute; the current limit is 120. Product decision pending."),
    ("TW-104", "Allow delivery windows shorter than 30 minutes", "Story", "In Review", "Low", "Tobias Lindgren",
     "Ines Calloway", "2026-09-22", "Northgate Brewing",
     "Northgate Brewing wants 15 minute delivery windows for pubs without a back door. Shipped behind a feature flag."),
    ("TW-105", "SAML login for Silverline Credit Union", "Story", "In Progress", "High", "Hana Okafor", "Marek Voss",
     "2026-10-01", "Silverline Credit Union",
     "Silverline Credit Union requires SAML single sign-on before it signs the renewal. Estimated 6 working days."),
    ("TW-106", "Import teachers from CSV", "Task", "Done", "Low", "Tobias Lindgren", "Priya Anand",
     "2026-08-27", "Aldermere Schools Trust",
     "Aldermere Schools Trust uploads teacher lists as CSV. Import added in 4.7.0."),
    ("TW-107", "Dark mode in the driver app", "Story", "To Do", "Low", "Tobias Lindgren", "Ines Calloway",
     "2026-10-12", "Harbor Freight Logistics", "Drivers at Harbor Freight Logistics ask for a dark mode at night."),
    ("TW-108", "Nightly backup took 9 hours", "Bug", "Done", "High", "Dev Raman", "Dev Raman",
     "2026-09-14", "", "The nightly backup ran for 9 hours on 2026-09-13. Cause: unindexed audit table. Index added."),
    ("TW-109", "Update TLS certificates before expiry", "Task", "Done", "Medium", "Dev Raman", "Dev Raman",
     "2026-09-30", "", "Certificates for api.tidewell.example renewed until 2027-09-30."),
    ("TW-110", "Prepare release 4.8", "Epic", "In Progress", "Medium", "Hana Okafor", "Hana Okafor",
     "2026-10-08", "", "Release 4.8 is planned for 2026-10-29. Contains the route export fix (TW-101) and SAML login (TW-105)."),
]
WIKI = [  # (Seiten-ID, Titel, Bereich, Autor, Datum, Text)
    ("40101", "Onboarding checklist for new sales hires", "Sales", "Priya Anand", "2026-08-04",
     "## First week\nOn day one request access to the CRM and the ticket system; approval takes one business day, "
     "everything else depends on it. On day two join the sales channel and shadow a discovery call. "
     "On day four give the demo to Priya Anand. The sales channel is faster than direct messages."),
    ("40102", "Refund policy", "Finance", "Greta Mills", "2026-05-11",
     "## Policy\nCustomers can cancel within 30 days of the first invoice for a full refund. After that, refunds are "
     "prorated for annual plans only. Refunds above 10.000 USD need approval from Greta Mills and a second signature "
     "from the CEO."),
    ("40103", "Pricing and discounts", "Sales", "Marek Voss", "2026-09-01",
     "## List prices (valid from 2026-09-01)\nStarter 12 USD per user and month, Business 24 USD, Enterprise on request. "
     "Sales may grant up to 10 percent discount alone; 10 to 20 percent needs the head of sales; above 20 percent "
     "needs the CEO."),
    ("40104", "Pricing and discounts - copy", "Sales", "Marek Voss", "2026-03-15",
     "## List prices (valid from 2026-03-15)\nStarter 10 USD per user and month, Business 20 USD, Enterprise on request. "
     "Sales may grant up to 15 percent discount alone. (Old version, kept as a draft.)"),
    ("40105", "Incident process", "Engineering", "Dev Raman", "2026-06-20",
     "## Severity\nSev1: customer-facing outage, page the on-call engineer immediately, status page update within "
     "15 minutes. Sev2: degraded service, fix within one business day. Sev3: everything else, normal backlog. "
     "After every Sev1 a written post-mortem is due within 5 working days."),
    ("40106", "Harbor Freight Logistics - Renewal Proposal", "Sales", "Ines Calloway", "2026-10-02",
     "## Proposal\nThree-year renewal of the Enterprise plan for Harbor Freight Logistics at 184.000 USD per year, "
     "including 24/7 support. Offered discount: 8 percent against list price. Decision maker: Elena Brandt, COO."),
    ("40107", "Silverline Credit Union - Security Review", "Security", "Marek Voss", "2026-09-25",
     "## Status\nSilverline Credit Union sent a 140 question security questionnaire. 96 are answered. Open: data "
     "residency (must stay in the EU), SAML single sign-on (see TW-105) and the penetration test report from 2026."),
    ("40108", "Maplewood Dental Group - Onboarding Notes", "Customer Success", "Dev Raman", "2026-07-10",
     "## Notes\nMaplewood Dental Group has 9 clinics. Reminders go out 48 hours and 4 hours before the appointment. "
     "Contact person: Dr. Jonas Reuter. They prefer calls in the morning."),
    ("40109", "Northgate Brewing - Lessons from the Pilot", "Customer Success", "Ines Calloway", "2026-08-30",
     "## Lessons\nThe pilot with Northgate Brewing ran for 8 weeks in 40 pubs. Late deliveries dropped from 18 to "
     "6 percent. The expansion to a second brewery was lost to a competitor on price."),
    ("40110", "Data retention", "Legal", "Greta Mills", "2026-04-02",
     "## Rule\nCustomer data is deleted 90 days after the contract ends. Backups are deleted after a further 35 days. "
     "Audit logs are kept for 7 years."),
]
SHAREPOINT = [  # (Guid, Dateiname, Pfad, Datum)
    ("a1f0-0001", "Corvid Analytics - Order Form.pdf", "/Shared/Sales/Corvid Analytics", "2026-06-12"),
    ("a1f0-0002", "Aldermere Schools Trust - Pilot Agreement.docx", "/Shared/Sales/Aldermere Schools Trust", "2026-09-15"),
    ("a1f0-0003", "Tidewell - Org Chart 2026.pdf", "/Shared/HR", "2026-01-08"),
]


def bauen():
    docs = []
    for i, (name, branche, owner, zweck) in enumerate(ACCOUNTS):
        docs.append({"id": f"salesforce:acct-{i}", "system": "crm", "titel": f"CRM-Account {name}", "datum": None,
                     "text": f"Salesforce Account {name} (acct-{i})\nBranche: {branche}\nAccount-Owner: {owner}"})
        docs.append({"id": f"slack:acct-{i}", "system": "slack", "titel": f"Slack-Kanal #{name.lower().replace(' ', '-')}",
                     "datum": None, "text": f"Slack-Kanal #{name.lower().replace(' ', '-')}\nZweck: {name}: {zweck}\n"
                     f"Thema: {branche} · account owner {owner}"})
    for i, a, zusatz, stage, betrag, close, wk, schritt in DEALS:
        name = f"{ACCOUNTS[a][0]} - {zusatz}"
        z = [f"Salesforce Opportunity {name} (deal-{i})", f"Account: {ACCOUNTS[a][0]} (acct-{a})", f"Stage: {stage}",
             f"Betrag: {betrag}", f"Close-Datum: {close}", f"Wahrscheinlichkeit: {wk}"]
        if schritt:
            z.append(f"Nächster Schritt: {schritt}")
        docs.append({"id": f"salesforce:deal-{i}", "system": "crm", "titel": f"CRM-Deal {name}", "datum": close,
                     "text": "\n".join(z)})
    for key, titel, typ, status, prio, bearb, melder, datum, kunde, text in JIRA:
        docs.append({"id": f"jira:{key}", "system": "jira", "titel": f"Jira {key}: {titel}", "datum": datum,
                     "text": f"Jira {key}: {titel}\nTyp: {typ}\nStatus: {status}\nPriorität: {prio}\nBearbeiter: {bearb}\n"
                     f"Melder: {melder}\nErstellt: {datum}\nBeschreibung:\n{text}"})
    for seite, titel, bereich, autor, datum, text in WIKI:
        docs.append({"id": f"confluence:{seite}", "system": "wiki", "titel": f"Confluence: {titel}", "datum": datum,
                     "text": f"Confluence-Seite {titel} (ID {seite})\nBereich: {bereich}\nAutor: {autor}  Stand: {datum}\n\n{text}"})
    for guid, datei, pfad, datum in SHAREPOINT:
        docs.append({"id": f"sharepoint:{guid}", "system": "sharepoint", "titel": f"SharePoint Datei {datei}", "datum": datum,
                     "text": f"SharePoint-Datei {datei}\nPfad: {pfad}/{datei}\nGeändert: {datum}\n"
                     "(Nur Metadaten, Dateiinhalt nicht im Korpus.)"})
    return docs


if __name__ == "__main__":
    ziel = Path(__file__).parent / "dokumente.jsonl"
    docs = bauen()
    ziel.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs))
    print(f"{len(docs)} Dokumente -> {ziel.name}")
