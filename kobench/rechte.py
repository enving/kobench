"""Rechte eines Datensatzes auswerten (`rechte.yaml` im Datensatz-Ordner, sonst `KOBENCH_RECHTE`).

Regeln: Glob-Muster (fnmatch) auf die Dokument-ID, die letzte passende Regel gilt.
Ein Nutzer sieht ein Dokument, wenn sich seine Kreise und die des Dokuments überschneiden.

    from kobench.rechte import darf, sichtbar
    darf("ben_support", "salesforce:deal-3")   # False

Format von rechte.yaml:

    kreise:  {alle: "Firmenöffentlich", vertrieb: "CRM, Vertriebskanäle", ...}
    quellen: [{muster: "salesforce:*", kreise: [vertrieb]}, ...]
    nutzer:  {ben_support: [alle, support], ...}
"""
import os
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import yaml

from .korpus import DATEN

RECHTE = Path(os.environ.get("KOBENCH_RECHTE") or DATEN / "rechte.yaml")


@lru_cache
def rechte(pfad=RECHTE):
    return yaml.safe_load(Path(pfad).read_text())


def kreise_fuer(doc_id, r=None):
    """Kreise eines Dokuments (frozenset); leer, wenn keine Regel passt. Die letzte passende Regel gilt."""
    r = r or rechte()
    treffer = frozenset()
    for regel in r["quellen"]:
        if fnmatchcase(doc_id, regel["muster"]):
            treffer = frozenset(regel["kreise"])
    return treffer


def darf(nutzer, doc_id, r=None):
    if nutzer is None:  # ohne Nutzer keine Einschränkung
        return True
    r = r or rechte()
    return bool(kreise_fuer(doc_id, r) & set(r["nutzer"][nutzer]))


def sichtbar(nutzer, doc_ids, r=None):
    """Filtert eine ID-Liste auf das, was der Nutzer sehen darf."""
    return [i for i in doc_ids if darf(nutzer, i, r)]
