"""Vertragstest: Jedes Harness liefert die vereinbarte Rückgabe, ohne API-Aufrufe.

Sprachmodell und Embeddings werden durch Attrappen ersetzt. Ein neues Harness in
kobench/harnesses.py (ALLE) oder per registrieren() wird automatisch mitgeprüft:  uv run pytest
"""
import hashlib
import inspect
import json

import numpy as np
import pytest

from kobench import harnesses, lauf, llm
from kobench.bewertung import FUER_RICHTER, leck_metriken, quellen_metriken, zitate
from kobench.korpus import fragen, nach_id

GESENDET = []  # alle Nachrichten, die an das (falsche) Sprachmodell gingen


def falsches_embed(texte):
    m = np.array([np.frombuffer(hashlib.sha256(t.encode()).digest(), dtype=np.uint8)[:16] for t in texte],
                 dtype=np.float32) + 1
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def falscher_chat(nachrichten, modell=None, werkzeuge=None, json_modus=False, max_tokens=1500, rolle="antwort"):
    GESENDET.extend(m.get("content") or "" for m in nachrichten)
    if json_modus:  # Richter
        return ({"role": "assistant", "content": json.dumps({"punkte": [{"punkt": "p", "erfuellt": True}],
                 "erfunden": False, "begruendung": "-"})}, {"prompt_tokens": 10, "completion_tokens": 5})
    if werkzeuge and not any(m.get("role") == "tool" for m in nachrichten):  # Agent: erst suchen, dann antworten
        return ({"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function",
                 "function": {"name": "suche", "arguments": '{"anfrage": "Corvid"}'}}]},
                {"prompt_tokens": 10, "completion_tokens": 2})
    return {"role": "assistant", "content": "Antwort [salesforce:deal-2]"}, {"prompt_tokens": 10, "completion_tokens": 5}


@pytest.fixture(autouse=True)
def attrappen(monkeypatch):
    GESENDET.clear()
    monkeypatch.setattr(llm, "chat", falscher_chat)
    monkeypatch.setattr(llm, "embed", falsches_embed)


@pytest.mark.parametrize("name", list(harnesses.ALLE))
def test_rueckgabe(name):
    h = harnesses.ALLE[name]
    assert h.titel and h.beschreibung
    assert "nutzer" in inspect.signature(h.antworte).parameters, "antworte(frage, nutzer=None) fehlt"
    erg = h.antworte("Wie ist der Stand bei Corvid Analytics?", nutzer="gast")
    assert isinstance(erg["antwort"], str) and erg["antwort"]
    assert isinstance(erg["kontext"], list)
    assert all(i in nach_id() or i.startswith("karte:") for i in erg["kontext"]), "unbekannte Kontext-IDs"
    assert isinstance(erg["schritte"], list)
    assert set(erg["tokens"]) == {"rein", "raus"}


def test_quellen_metriken():
    f = {"quellen": ["salesforce:deal-2"], "auch_ok": []}
    m = quellen_metriken(f, {"kontext": ["salesforce:deal-2"], "antwort": "x [salesforce:deal-2, jira:XX-1]"})
    assert m["gefunden"] == 1.0 and m["zitiert"] == 1.0 and m["zitate_ungueltig"] == ["jira:XX-1"]
    assert zitate("a [a:b; c:d] [e:f]") == ["a:b", "c:d", "e:f"]
    assert quellen_metriken({"quellen": []}, {"kontext": [], "antwort": "-"})["gefunden"] is None


def test_leck_metriken():
    f = {"nutzer": "gast", "verboten": ["salesforce:deal-0"]}
    erg = {"kontext": ["salesforce:deal-0", "salesforce:deal-2", "confluence:40101", "karte:pipeline"]}
    m = leck_metriken(f, erg)
    assert m["leck_verboten"] == ["salesforce:deal-0"]
    assert m["leck_streng"] == ["salesforce:deal-0", "salesforce:deal-2"]  # CRM ist Kreis vertrieb, Gast hat nur "alle"
    assert leck_metriken({"quellen": []}, erg) == {}
    assert leck_metriken(f, {"kontext": ["confluence:40101"]}) == {"leck_verboten": [], "leck_streng": []}


@pytest.mark.parametrize("name", list(harnesses.ALLE))
def test_hintergrund_geht_nirgends_hin(name):
    """`hintergrund` (Antwort mit vollen Rechten) darf weder ans Harness noch an den Richter."""
    mit = [f for f in fragen() if f.get("hintergrund")]
    assert mit
    for f in mit:
        GESENDET.clear()
        e = lauf.bearbeite(name, dict(f, hintergrund="GEHEIM-HINTERGRUND-4711"))
        assert e["nutzer"] == f["nutzer"] and "leck_streng" in e["bewertung"]
        assert "GEHEIM-HINTERGRUND-4711" not in " ".join(GESENDET)
        assert "GEHEIM" not in json.dumps(e, ensure_ascii=False)
    assert "hintergrund" not in FUER_RICHTER and "verboten" not in FUER_RICHTER


def test_nutzer_wird_durchgereicht(monkeypatch):
    gesehen = []
    h = harnesses.ALLE["ohne"]
    monkeypatch.setattr(h, "antworte", lambda frage, nutzer=None: gesehen.append(nutzer) or
                        {"antwort": "x", "kontext": [], "schritte": [], "tokens": {"rein": 0, "raus": 0}})
    lauf.bearbeite("ohne", next(f for f in fragen() if f["id"] == "q12"))
    lauf.bearbeite("ohne", fragen()[0])
    assert gesehen == ["gast", None]


def test_eigenes_harness_anschliessen(monkeypatch):
    monkeypatch.setattr(harnesses, "ALLE", dict(harnesses.ALLE))

    class Eigenes:
        name, titel, beschreibung = "eigenes", "Eigenes Harness", "Immer dieselbe Antwort."

        def antworte(self, frage, nutzer=None):
            return {"antwort": "ja [salesforce:deal-2]", "kontext": ["salesforce:deal-2"], "schritte": [],
                    "tokens": {"rein": 0, "raus": 0}}

    harnesses.registrieren(Eigenes())
    with pytest.raises(ValueError):
        harnesses.registrieren(type("Doppelt", (Eigenes,), {})())  # Name schon vergeben
    with pytest.raises(ValueError):
        harnesses.registrieren(type("Leer", (), {"name": "x", "titel": "x", "beschreibung": "x"})())
