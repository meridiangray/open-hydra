"""Shared constants and country/schema helpers for the compiler."""
from __future__ import annotations
from hydra import schema, standards


MEDIA_PROPS = ("fileName",)       # FtM's own file field on a document, page or other evidence record


# schema-class badges every node gets regardless of rules
DEFAULT_HINTS = [
    {"match": {"schema": "Company"},      "set": {"badge": "building"}},
    {"match": {"schema": "Organization"}, "set": {"badge": "users"}},
    {"match": {"schema": "PublicBody"},   "set": {"badge": "landmark"}},
    {"match": {"schema": "Person"},       "set": {"badge": "user"}},
]


FORMER_PROPS = {"deathDate", "dissolutionDate", "endDate", "deregistrationDate"}


def country_code(v: str) -> str:
    c = standards.country_code(v)
    return c if len(c) == 2 else ""


def orgish(s) -> bool:
    return (schema.is_a(s, "Organization") or schema.is_a(s, "PublicBody")
            or (schema.is_a(s, "LegalEntity") and not schema.is_a(s, "Person")))
