"""Beispielfirma: Fragen sind am Korpus belegt, Rechte sind vollständig, der Lauf-Bericht entsteht ohne API."""
import json
from fnmatch import fnmatchcase

from kobench import harnesses, lauf, llm
from kobench.korpus import dokumente, fragen, nach_id
from kobench.rechte import darf, kreise_fuer, rechte

from .test_vertrag import falscher_chat, falsches_embed


def test_fragen_quellen_existieren():
    ids = [f["id"] for f in fragen()]
    assert len(ids) == len(set(ids)) >= 10
    for f in fragen():
        for q in f["quellen"] + f.get("auch_ok", []) + f.get("verboten", []):
            assert q in nach_id(), f"{f['id']}: {q} nicht im Korpus"
        assert f["punkte"] and f["gold"] and f["typ"], f["id"]


def test_dokumente_wohlgeformt():
    assert len(dokumente()) == len(nach_id())  # keine doppelten IDs
    for d in dokumente():
        assert d["id"].split(":")[0] in {"salesforce", "slack", "jira", "confluence", "sharepoint"}


def test_jede_id_hat_kreise_und_jede_regel_greift():
    r = rechte()
    assert not [i for i in nach_id() if not kreise_fuer(i, r)]
    for regel in r["quellen"]:
        assert set(regel["kreise"]) <= set(r["kreise"]), regel
    for name, kreise in r["nutzer"].items():
        assert "alle" in kreise and set(kreise) <= set(r["kreise"]), name


def test_rechtefragen_stimmig():
    for f in fragen():
        if f["typ"] == "rechte":
            assert f["nutzer"] in rechte()["nutzer"]
            assert all(darf(f["nutzer"], q) for q in f["quellen"]), f["id"]
        if f["id"] == "q12":
            assert not any(darf(f["nutzer"], q) for q in f["verboten"])


def test_lauf_und_bericht(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", falscher_chat)
    monkeypatch.setattr(llm, "embed", falsches_embed)
    ziel = tmp_path / "lauf"
    lauf.laufe(["ohne", "bm25", "kundenakte"], {"q01", "q12"}, ziel, 1)
    (ziel / "lauf.json").write_text(json.dumps({"antwortmodell": "x", "richter": "y", "commit": "-", "datensatz": "beispiel"}))
    lauf.bericht(ziel)
    text = (ziel / "bericht.md").read_text()
    assert "## Gesamt" in text and "## Leck-Quote" in text and "Klassisches RAG" in text
