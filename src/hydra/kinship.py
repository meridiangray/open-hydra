"""kinship.py — what a Family `relationship` word says (.hydra/rules/kinship.yaml).

A Family record's word describes the relative from the person's side ("father": the relative is
the person's father). Which words mean parent, child, sibling or spouse, and which gender each
gives, is read from the rules file (the archive's own, else the template's), so the tree, the
wiki and the checks work in any language an archive's sources use.

    load(root)            -> Kinship
    Kinship.is_(w, kind)  -> does word `w` say the relative is a parent / child / sibling / spouse
    Kinship.gender(w)     -> "male" / "female" / None, as the word says it
    Kinship.name(kind, g) -> how a page words a relative of that kind and gender ("son", "sister")
    Kinship.base(verb)    -> the word in a relation's verb ("father of" -> "father")
"""
from __future__ import annotations

from pathlib import Path

from hydra import layout, resources, yamlcache

KINDS = ("parent", "child", "sibling", "spouse")


def path(root) -> Path:
    own = Path(root) / layout.KINSHIP if root else None
    return own if own and yamlcache.is_file(own) else resources.TEMPLATE / layout.KINSHIP


def load(root=None) -> "Kinship":
    f = path(root)
    doc = yamlcache.load(f) if yamlcache.is_file(f) else None
    return Kinship(doc if isinstance(doc, dict) else {})


class Kinship:
    def __init__(self, doc: dict):
        self.words = {str(k).strip().lower(): (v if isinstance(v, dict) else {}) for k, v in (doc.get("words") or {}).items()}
        self.names = {str(k): (v if isinstance(v, dict) else {}) for k, v in (doc.get("names") or {}).items()}

    @staticmethod
    def base(verb) -> str:
        """A relation's verb as its word: "father of" (the relative's side) -> "father"."""
        v = str(verb or "").strip().lower()
        return v[:-3] if v.endswith(" of") else v

    def is_(self, word, kind: str) -> bool:
        return (self.words.get(self.base(word)) or {}).get("is") == kind

    def gender(self, word) -> str | None:
        return (self.words.get(self.base(word)) or {}).get("gender")

    def of_kind(self, kind: str) -> set[str]:
        return {w for w, d in self.words.items() if d.get("is") == kind}

    def name(self, kind: str, gender: str | None) -> str:
        n = self.names.get(kind) or {}
        return n.get(gender or "other") or n.get("other") or kind
