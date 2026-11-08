"""vocab.py — controlled words for string properties (.hydra/rules/vocabularies.yaml).

A `status` or a `capacity` is free text in FtM, but the tools act on some of its words:
a former stake is not counted as current, a reported one is flagged where its share is
shown. The words and what each means are read from the rules file (the archive's own,
else the one hydra ships), so no code names them. The wiki, `wiki check` and the MCP
tools all read them from here.

    load(root)                       -> {name: {"applies_to": [...], "values": {...}}}
    lookup(vocabs, schema, prop)     -> (name, vocabulary) covering schema.prop, or (None, None)
    meaning(vocabs, schema, prop, v) -> the value's entry ({} when not listed)
    outside(vocabs, schema, prop, v) -> True when a vocabulary covers the property and v is not in it
"""
from __future__ import annotations

from pathlib import Path

from hydra import layout, resources, yamlcache
from hydra import schema as hschema


def path(root) -> Path:
    """The file in effect: the archive's own, else the one hydra ships."""
    own = Path(root) / layout.VOCABULARIES if root else None
    return own if own and yamlcache.is_file(own) else resources.TEMPLATE / layout.VOCABULARIES


def load(root) -> dict:
    f = path(root)
    if not yamlcache.is_file(f):
        return {}
    doc = yamlcache.load(f) or {}
    out = {}
    for name, v in (doc.items() if isinstance(doc, dict) else ()):
        if isinstance(v, dict):
            values = {str(k).lower(): (m if isinstance(m, dict) else {}) for k, m in (v.get("values") or {}).items()}
            out[str(name)] = {"applies_to": [str(a) for a in v.get("applies_to") or []], "values": values}
    return out


def lookup(vocabs: dict, schema: str, prop: str):
    """The vocabulary covering `schema.prop`, its own schema first, then the ones it extends."""
    for s in hschema.ancestors(schema) or (schema,):
        for name, v in vocabs.items():
            if f"{s}.{prop}" in v["applies_to"]:
                return name, v
    return None, None


def meaning(vocabs: dict, schema: str, prop: str, value) -> dict:
    _, v = lookup(vocabs, schema, prop)
    return (v or {}).get("values", {}).get(str(value or "").strip().lower(), {}) if value else {}


def outside(vocabs: dict, schema: str, prop: str, value) -> bool:
    _, v = lookup(vocabs, schema, prop)
    return bool(v and value and str(value).strip().lower() not in v["values"])


def covered(vocabs: dict) -> list[str]:
    """Every property some vocabulary covers, as `Schema.prop`."""
    return sorted({a for v in vocabs.values() for a in v["applies_to"]})
