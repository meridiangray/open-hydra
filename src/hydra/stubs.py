"""stubs.py — names that link to no record, and graduating one into an entity.

A link field (`Membership.member`, `Family.relative`...) holds a name. When the
name matches no record, the build has nothing to link it to: each such value is
an `unresolved` reference row with no candidates, and the record it names has
no node. That name is a stub.

Graduating a stub is a decision, never data entry: `stub-<slug>: <Schema>` in
verdicts.yaml (the slug is the name, case, accents and punctuation ignored:
`Gretchen Schwartz` -> `gretchen-schwartz`). The build then adds one record,
id `stub:<slug>`, with the name as it is written in the data, before links are
resolved, so every value with that name links to it. A stub never survives a
merge: a real record with the same name keeps its own id and takes the stub in.
`reset --only stubs` undoes them all."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from hydra import layout, schema
from hydra.identity import types

KEY = "stub-"
PREFIX = "stub"                                   # a stub's id: stub:<slug>
COLLECTION = "stub"


def slug(name: str) -> str:
    return "-".join(types.norm_text(str(name)).split())


def key(name: str) -> str:
    return KEY + slug(name)


def is_stub(rid) -> bool:
    return isinstance(rid, str) and rid.startswith(PREFIX + ":")


def decided(verdicts: dict) -> dict[str, str]:
    """{slug: schema} of the stubs the decisions graduate."""
    return {k[len(KEY):]: v for k, v in (verdicts or {}).items()
            if isinstance(k, str) and k.startswith(KEY) and isinstance(v, str)}


def _link_values(records: list[dict]):
    """(value, schema.prop) of every entity-typed value in the records."""
    for r in records:
        pdefs = schema.resolve(r["schema"])["props"] if r.get("schema") in schema.SCHEMA else {}
        for p, vals in (r.get("properties") or {}).items():
            if (pdefs.get(p) or {}).get("type") == "entity":
                for v in vals:
                    if isinstance(v, str) and v.strip():
                        yield v, f"{r['schema']}.{p}"


def records_for(records: list[dict], graduate: dict[str, str]) -> list[dict]:
    """The records the build adds for `graduate` ({slug: schema}): one per slug
    some link value names, spelled as the data spells it most often. A slug
    nothing names, or an unknown schema, adds nothing (lint says so)."""
    spellings: dict[str, Counter] = {}
    for v, _ in _link_values(records):
        s = slug(v)
        if s in graduate:
            spellings.setdefault(s, Counter())[v] += 1
    return [{"id": f"{PREFIX}:{s}", "schema": graduate[s], "properties": {"name": [c.most_common(1)[0][0]]},
             "_collection": COLLECTION, "_stub": True}
            for s, c in sorted(spellings.items()) if graduate[s] in schema.SCHEMA]


def fits(groups) -> str | None:
    """The most specific schema every link field (`Schema.prop`) can point at,
    or None when their ranges do not lie on one line."""
    ranges = []
    for g in groups:
        sname, _, prop = g.partition(".")
        r = ((schema.resolve(sname)["props"].get(prop) or {}).get("range")) if sname in schema.SCHEMA else None
        if r:
            ranges.append(r)
    best = None
    for r in ranges:
        if best is None or schema.is_a(r, best):
            best = r
        elif not schema.is_a(best, r):
            return None
    return best


def found(root) -> list[dict]:
    """The stubs of the last build: [{slug, name, links, fields, fits}], each a
    name some link values hold that no record has; most links first."""
    schema.load(root=root)                        # `fits` reads the fields' ranges
    p = Path(root) / layout.LEDGER_JSONL
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if p.is_file() else []
    by: dict[str, dict] = {}
    for r in rows:
        if r.get("rel") == "references" and r.get("status") == "unresolved" and not r.get("candidates"):
            s = slug(r.get("value") or "")
            if not s:
                continue
            e = by.setdefault(s, {"slug": s, "spellings": Counter(), "links": 0, "fields": []})
            e["spellings"][str(r["value"])] += 1
            e["links"] += 1
            if r.get("group") and r["group"] not in e["fields"]:
                e["fields"].append(r["group"])
    out = []
    for s, e in by.items():
        out.append({"slug": s, "name": e["spellings"].most_common(1)[0][0], "links": e["links"],
                    "fields": e["fields"], "fits": fits(e["fields"])})
    return sorted(out, key=lambda e: (-e["links"], e["name"].lower()))
