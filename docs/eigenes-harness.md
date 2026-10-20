# Eigenes Harness anschließen

Ein Harness ist ein Objekt mit vier Attributen. Mehr verlangt kobench nicht.

```python
class MeinSystem:
    name = "mein"                 # kurz, eindeutig, wird im Bericht und bei -H benutzt
    titel = "Mein System"         # Anzeigename
    beschreibung = "Ein Satz, was anders ist."

    def antworte(self, frage, nutzer=None):
        ...
        return {
            "antwort": "Text mit [quell-id]-Zitaten",
            "kontext": ["jira:TW-101", ...],     # IDs der Dokumente, die das Modell zu sehen bekam
            "schritte": [{"suche": "...", "treffer": [...]}],   # Protokoll, frei
            "tokens": {"rein": 1200, "raus": 150},
        }
```

## Was die Rückgabe bedeutet

- `antwort`: deutscher Text. Quellen als `[system:schlüssel]` (auch mehrere in einer Klammer, mit Komma oder Semikolon).
- `kontext`: **alles, was das Modell gesehen hat**, als Dokument-IDs aus dem Korpus. Daraus entstehen "Quellen gefunden" und
  die Leck-Quote. Wer hier weniger angibt, als das System tatsächlich abgerufen hat, fälscht sein Ergebnis. Verdichtete
  Zwischenstufen dürfen IDs mit Präfix `karte:` haben; ihre Ursprungs-IDs müssen trotzdem im Kontext stehen.
- `tokens`: gemessener Verbrauch (0, wenn das System ihn nicht meldet; dann ist die Spalte nicht vergleichbar).
- `nutzer`: Name aus `rechte.yaml`, wenn die Frage einen hat. Unterstützt dein System Rechte, filtere damit. Unterstützt es
  sie nicht, ignoriere ihn: genau das misst die Leck-Quote.

## Fairness

Für einen Vergleich muss dasselbe Antwortmodell und derselbe Systemprompt gelten. Der einfachste Weg ist, den letzten Schritt
von kobench zu benutzen:

```python
from kobench.harnesses import _antwort
return _antwort(frage, kontext_text, kontext_ids, schritte)
```

Ein System, das ein eigenes Modell mitbringt (z. B. ein Produkt mit eingebautem Chat), ist **kein** Vergleich der Anbindung,
sondern von Anbindung plus Modell. Das im Bericht festhalten.

## Anschließen

Im eigenen Paket eine Liste `HARNESSES` anlegen und beim Lauf mit `-m` laden:

```bash
uv run kobench -m mein_paket -H mein,bm25
```

oder im Code `kobench.harnesses.registrieren(MeinSystem())`. Namen müssen eindeutig sein.

## Vertragstest für das eigene Paket

```python
import pytest
from kobench import harnesses
from mein_paket import HARNESSES

@pytest.mark.parametrize("h", HARNESSES)
def test_vertrag(h):
    erg = h.antworte("Wie ist der Stand bei Corvid Analytics?", nutzer="gast")
    assert erg["antwort"] and isinstance(erg["kontext"], list) and set(erg["tokens"]) == {"rein", "raus"}
```

## Anbieter-Adapter

Adapter für ein bestimmtes Produkt gehören in ein eigenes Repo, das `kobench` als Abhängigkeit nutzt und `HARNESSES`
bereitstellt. So bleibt kobench der Benchmark, und Produkte werden nicht durch Adapter im Messprogramm bevorzugt.
Der Adapter sollte seine Einrichtung (Konto, Schlüssel, Kosten, Kontingent) selbst dokumentieren und Kosten beim Lauf melden.
