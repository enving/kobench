"""Datensatz laden (Dokumente, Fragen, Firmenangaben) und gemeinsame Suchbausteine (BM25, Dense, Rangfusion).

Ein Datensatz ist ein Ordner (Standard `daten/beispiel`, sonst `KOBENCH_DATEN=<ordner>`):

  dokumente.jsonl   ein Dokument je Zeile: {"id", "system", "titel", "datum", "text"}
  fragen.yaml       der Fragenkatalog (Format: docs/format.md)
  firma.yaml        optional: {"name": "...", "stichtag": "15.10.2026"}
  rechte.yaml       optional: wer welche Dokumente sehen darf (nur für Fragen mit `nutzer`)
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from rank_bm25 import BM25Okapi

WURZEL = Path(__file__).resolve().parent.parent
_BEISPIEL = WURZEL / "daten/beispiel" if (WURZEL / "daten/beispiel").exists() else Path(__file__).parent / "_beispiel"
DATEN = Path(os.environ.get("KOBENCH_DATEN") or _BEISPIEL)
if not DATEN.is_absolute():
    DATEN = (Path.cwd() / DATEN) if (Path.cwd() / DATEN).exists() else WURZEL / DATEN
KORPUS = DATEN / "dokumente.jsonl"
FRAGEN = DATEN / "fragen.yaml"


@lru_cache
def firma():
    datei = DATEN / "firma.yaml"
    angaben = yaml.safe_load(datei.read_text()) if datei.exists() else {}
    return {"name": angaben.get("name", "der Firma"), "stichtag": str(angaben.get("stichtag", "heute"))}


@lru_cache
def dokumente():
    docs = [json.loads(z) for z in KORPUS.read_text().splitlines() if z.strip()]
    for d in docs:
        fehlt = {"id", "system", "titel", "text"} - set(d)
        if fehlt:
            raise ValueError(f"{KORPUS}: Dokument {d.get('id', '?')} ohne Felder {sorted(fehlt)}")
    return docs


@lru_cache
def nach_id():
    return {d["id"]: d for d in dokumente()}


def katalog_pfad(katalog=None):
    """Pfad eines Fragenkatalogs: ohne Angabe `fragen.yaml` des Datensatzes, sonst eine YAML-Datei
    (Pfad oder Name relativ zum Datensatz-Ordner, mit oder ohne `.yaml`)."""
    if not katalog:
        return FRAGEN
    for kandidat in (Path(katalog), DATEN / str(katalog), DATEN / f"{katalog}.yaml"):
        if kandidat.is_file():
            return kandidat
    raise FileNotFoundError(f"Fragenkatalog {katalog!r} nicht gefunden (Pfad oder Datei im Datensatz-Ordner {DATEN})")


def fragen(katalog=None):
    """Fragenkatalog laden (Format: docs/format.md)."""
    return yaml.safe_load(katalog_pfad(katalog).read_text())


def tokens(text):
    return re.findall(r"[a-z0-9äöüß][a-z0-9äöüß\-\.]*[a-z0-9]|[a-z0-9]", text.lower())


class Index:
    """BM25 und optional Dense (Embeddings) über eine Dokumentliste."""

    def __init__(self, docs, dense=False):
        self.docs = docs
        self.bm25 = BM25Okapi([tokens(d["titel"] + " " + d["text"]) for d in docs])
        self.vek = None
        if dense:
            from . import llm
            self.vek = llm.embed([d["titel"] + "\n" + d["text"] for d in docs])

    def bm25_suche(self, anfrage, k=8):
        s = self.bm25.get_scores(tokens(anfrage))
        return [self.docs[i] for i in np.argsort(-s)[:k] if s[i] > 0]

    def dense_suche(self, anfrage, k=8):
        from . import llm
        q = llm.embed([anfrage])[0]
        s = self.vek @ q
        return [self.docs[i] for i in np.argsort(-s)[:k]]

    def hybrid_suche(self, anfrage, k=8, tiefe=40):
        """Reciprocal Rank Fusion aus BM25 und Dense."""
        punkte = {}
        for liste in (self.bm25_suche(anfrage, tiefe), self.dense_suche(anfrage, tiefe)):
            for rang, d in enumerate(liste):
                punkte[d["id"]] = punkte.get(d["id"], 0) + 1 / (60 + rang)
        ids = sorted(punkte, key=punkte.get, reverse=True)[:k]
        index = {d["id"]: d for d in self.docs}
        return [index[i] for i in ids]


def als_kontext(docs, max_zeichen=2500):
    return "\n\n".join(f"[{d['id']}] {d['titel']}\n{d['text'][:max_zeichen]}" for d in docs)
