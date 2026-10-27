"""Shared constants and name-normalization helpers for the compiler."""
from __future__ import annotations
import re
from hydra import schema
from hydra.identity.types import norm_text


MEDIA_PROPS = ("fileName",)       # FtM's own file field on a document, page or other evidence record


# schema-class badges every node gets regardless of rules
DEFAULT_HINTS = [
    {"match": {"schema": "Company"},      "set": {"badge": "building"}},
    {"match": {"schema": "Organization"}, "set": {"badge": "users"}},
    {"match": {"schema": "PublicBody"},   "set": {"badge": "landmark"}},
    {"match": {"schema": "Person"},       "set": {"badge": "user"}},
]


FORMER_PROPS = {"deathDate", "dissolutionDate", "endDate", "deregistrationDate"}





_COUNTRY_NAMES = {
    "united kingdom": "gb", "great britain": "gb", "england": "gb", "uk": "gb",
    "united states": "us", "usa": "us", "united states of america": "us",
    "russia": "ru", "ukraine": "ua", "hungary": "hu", "czech republic": "cz",
    "czechia": "cz", "france": "fr", "germany": "de", "israel": "il",
    "sweden": "se", "switzerland": "ch", "austria": "at", "italy": "it",
    "slovakia": "sk", "poland": "pl", "canada": "ca", "luxembourg": "lu",
    "paraguay": "py", "uruguay": "uy", "channel islands": "gb",
    "alderney": "gb", "greece": "gr", "netherlands": "nl", "spain": "es",
    "belgium": "be", "panama": "pa", "cyprus": "cy", "liechtenstein": "li",
    "uzbekistan": "uz",
}


def country_code(v: str) -> str:
    n = norm_text(v).replace(" ", "")
    if re.fullmatch(r"[a-z]{2}", n):
        return n
    return _COUNTRY_NAMES.get(norm_text(v), "")


def orgish(s) -> bool:
    return (schema.is_a(s, "Organization") or schema.is_a(s, "PublicBody")
            or (schema.is_a(s, "LegalEntity") and not schema.is_a(s, "Person")))
