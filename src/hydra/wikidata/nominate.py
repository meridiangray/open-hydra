"""nominate.py — the claims the map does not read yet, and what each could fill.

    suggest(schema_name, prop, taken)   -> [(field, score)]: fields of a schema a Wikidata property could fill
    unread_report(unread, props, rules) -> {"fits": [...], "ids": [...], "other": [...]}

A suggestion needs a field whose type the property's datatype can fill and whose name or label shares a
meaningful word with the property's label, so it is a prompt for a person, not an answer. A web address
can only be a `website` or a `sourceUrl`. Identifiers are grouped apart: they are keys (keys.yaml), not fields.
Each row: {pid, label, description, datatype, formatter, items, claims, example, schemas, fields}."""
from __future__ import annotations

import re

from hydra import schema

DATATYPE_FITS = {                        # Wikidata datatype -> the FtM field types it can fill
    "time": {"date"}, "quantity": {"number"}, "external-id": {"identifier"}, "url": {"url"},
    "wikibase-item": {"string", "country", "language", "gender", "name", "address", "entity"},
    "string": {"string", "identifier", "name", "address", "email", "phone"},
    "monolingualtext": {"string", "name", "text"},
}
URL_FIELDS = ("website", "sourceUrl")
GENERIC = {"main", "topic", "category", "status", "name", "short", "type", "code", "described", "source",
           "date", "number", "official", "list", "from", "for", "the", "and", "has", "its", "this", "that",
           "value", "end", "start", "class", "instance", "named", "native", "language", "used"}


def _words(text) -> set[str]:
    camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return {w for w in re.findall(r"[a-z]+", camel.lower()) if len(w) > 2}


def suggest(sname: str, prop: dict, taken=()) -> list[tuple[str, int]]:
    """Fields of `sname` the property could fill, best first. A field the map already fills from another
    property (`taken`) is left out."""
    fields = schema.resolve(sname)["props"]
    if prop["datatype"] == "url":
        return [(f, 1) for f in URL_FIELDS if f in fields]
    fits = DATATYPE_FITS.get(prop["datatype"], set())
    want = _words(prop["label"]) - GENERIC
    out = []
    for field, d in fields.items():
        if d["type"] not in fits or field in taken or d.get("hidden"):
            continue
        score = len(want & (_words(field) | _words(d.get("label", ""))))
        if score:
            out.append((field, score))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def _filled(rules, sname) -> set[str]:
    table = {**rules["common"], **(rules["properties"].get(sname) or {})}
    return {v if isinstance(v, str) else (v or {}).get("to") for v in table.values()}


def unread_report(unread: dict, props: dict, rules: dict) -> dict:
    """Group the unread claims; each group ordered by how many items carry the property."""
    rows: dict[str, dict] = {}
    for (sname, pid), u in unread.items():
        p = props.get(pid) or {"label": "", "description": "", "datatype": "", "formatter": ""}
        row = rows.setdefault(pid, {"pid": pid, **p, "items": set(), "claims": 0, "example": u["example"],
                                    "schemas": set(), "fields": {}})
        row["items"] |= u["items"]
        row["claims"] += u["claims"]
        row["schemas"].add(sname)
        for field, score in suggest(sname, p, _filled(rules, sname)):
            row["fields"][f"{sname}.{field}"] = score
    groups = {"fits": [], "ids": [], "other": []}
    for row in sorted(rows.values(), key=lambda r: (-len(r["items"]), -r["claims"], r["pid"])):
        row["items"] = len(row["items"])
        row["fields"] = [f for f, _ in sorted(row["fields"].items(), key=lambda x: (-x[1], x[0]))]
        groups["ids" if row["datatype"] == "external-id" else "fits" if row["fields"] else "other"].append(row)
    return groups
