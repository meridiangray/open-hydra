"""query.py — the words `claims` and `node find` take: types and search terms,
in any order.

    hydra-ctl claims person tikrit
    hydra-ctl node find tikrit Person
    hydra-ctl claims "walter white" --type person

A word that names an FtM schema, in any capitalisation (`person`, `Person`,
`PERSON`), keeps that type and its subtypes; several such words keep any of
them. `--type` does the same and is just as forgiving. Every other word is
part of the search, joined in order: `claims walter white` and
`claims "walter white"` look for the same thing. To search for a word that is
also a type name (`event`), quote it together with another word.

The search matches a node's names first (see each command for its ranking),
then the values of its other fields: `tikrit` finds a person whose
`birthPlace` is "Tikrit". How far it looks is the search mode: `all` (the
default), `no-text` (not free-text fields: notes, description, summary...) or
`names` (names and ids only). `--no-text` and `--names` set it for one command,
`search:` in hydra.yaml for the archive."""
from __future__ import annotations

from pathlib import Path

from hydra import layout, schema, yamlcache
from hydra.identity import types

SEARCH = ("all", "no-text", "names")


def add_search_flags(ap) -> None:
    """`--names` / `--no-text` on a command that searches."""
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--names", action="store_true", help="search names and ids only")
    g.add_argument("--no-text", action="store_true", help="search every field but free text (notes, description...)")


def search_mode(root, a=None) -> str:
    """The search mode: the command's flag, else `search:` in hydra.yaml, else `all`."""
    if a is not None and getattr(a, "names", False):
        return "names"
    if a is not None and getattr(a, "no_text", False):
        return "no-text"
    p = Path(root) / layout.MANIFEST
    doc = (yamlcache.load(p) or {}) if p.is_file() else {}
    got = doc.get("search") if isinstance(doc, dict) else None
    return got if got in SEARCH else "all"


def schema_named(word: str) -> str | None:
    """The schema `word` names, ignoring capitalisation, or None (schema loaded)."""
    if word in schema.SCHEMA:
        return word
    low = word.lower()
    return next((s for s in schema.SCHEMA if s.lower() == low), None)


def split(words, given_type: str = "") -> tuple[list[str], str]:
    """-> (the types asked for, the search text). `given_type` is `--type`'s value."""
    kinds, terms = [], []
    if given_type:
        kind = schema_named(given_type)
        if not kind:
            raise SystemExit(f"hydra: no schema '{given_type}'")
        kinds.append(kind)
    for w in words:
        kind = schema_named(w) if " " not in w else None
        if kind:
            kinds.append(kind)
        else:
            terms.append(w)
    return list(dict.fromkeys(kinds)), " ".join(terms).strip()


def of_type(node_schema: str, kinds: list[str]) -> bool:
    return not kinds or any(schema.is_a(node_schema or "", k) for k in kinds)


def text_fields(props: dict, schema_name: str, skip=(), free_text: bool = True) -> list[str]:
    """The properties a search reads: all but `skip` and links (an entity-typed
    value points at another record; it says nothing about this one), and with
    `free_text=False` not the free-text ones (FtM type `text`)."""
    pdefs = schema.resolve(schema_name)["props"] if schema_name in schema.SCHEMA else {}
    kind = lambda p: (pdefs.get(p) or {}).get("type")
    return [p for p in sorted(props) if p not in skip and kind(p) != "entity" and (free_text or kind(p) != "text")]


def field_hit(props: dict, text: str, skip=(), schema_name: str = "", free_text: bool = True) -> tuple[str, str] | None:
    """(property, value) of the first field value holding every word of `text`
    (case, accents and punctuation ignored); names in `skip`, and links, left out."""
    _, qw = types.name_key(text)
    if not qw:
        return None
    for p in text_fields(props, schema_name, skip, free_text):
        for v in props.get(p) or []:
            if isinstance(v, str) and qw <= types.name_key(v)[1]:
                return p, v
    return None
