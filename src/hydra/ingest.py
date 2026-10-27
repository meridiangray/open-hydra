"""ingest.py — reading records, and namespacing their ids.

Parsing: `parse_records()` reads `collections/*.json` and `*.jsonld` (entity
arrays, `{entities: [...]}`, bare objects, FtM JSON lines, or exchange-format
`{entity, composed, statements}`) into `{id, schema, properties: {p: [v]}}`.

Prefixes: ids are namespaced `<prefix>:<local id>`, one prefix per collection or source.
Nothing is ever generated. An id that already reads `<prefix>:<local id>` keeps
its prefix as its prefix; any other id gets its collection's prefix, taken from
`collections/manifest.json` (`collections.<name>.prefix`) or made from the
collection name and written back. Entity-typed values that are literal ids of
another record are rewritten with that record's prefix: the pointer's own
collection if it has the id, else the one other collection that does; an id
held by several other collections is left alone and reported. Names are never
touched. Verdicts filed under unprefixed ids no longer match after tagging, so
prefix first, then review."""
from __future__ import annotations

import json
import re
from collections import defaultdict

from hydra import schema



def parse_records(text: str) -> list[dict]:
    text = text.strip()
    try:
        data = json.loads(text) if text else []
        items = data if isinstance(data, list) else data.get("entities", [data])
    except json.JSONDecodeError:            # FTM JSON lines
        items = [json.loads(l) for l in text.splitlines() if l.strip()]
    out = []
    for r in items or []:
        if not isinstance(r, dict):
            continue
        if r.get("id"):
            rec = {"id": r["id"], "schema": r.get("schema") or "Thing",
                   "properties": _props(r.get("properties"))}
            if "_meta" in r:
                rec["_meta"] = r["_meta"]
            upstream = [str(x) for x in r.get("referents") or [] if x] if isinstance(r.get("referents"), list) else []
            if upstream:                         # ids an upstream tool (OpenSanctions, nomenklatura) merged into it
                rec["_referents"] = upstream
            stmts = [s for s in r.get("statements") or []
                     if isinstance(s, dict) and s.get("prop") is not None]
            if stmts:                            # re-ingested entity_sources
                rec["statements"] = stmts
            out.append(rec)
        elif isinstance(r.get("entity"), dict) \
                and (r.get("composed") or r.get("statements")):
            # exchange.md's entity_sources: {entity, composed, statements}.
            # composed -> properties; statements ride the record so the
            # claims fuzz can source each (prop, value) properly.
            e, props = r["entity"], _props(r.get("composed"))
            stmts = [s for s in r.get("statements") or []
                     if isinstance(s, dict) and s.get("prop") is not None]
            if r.get("composed") is None:        # no fold shipped? make one
                for s in stmts:
                    props.setdefault(s["prop"], [])
                    if str(s.get("value")) not in props[s["prop"]]:
                        props[s["prop"]].append(str(s.get("value")))
            if not e.get("id"):
                continue
            rec = {"id": e["id"], "schema": e.get("schema") or "Thing",
                   "properties": props}
            if "_meta" in r:
                rec["_meta"] = r["_meta"]
            if stmts:
                rec["statements"] = stmts
            out.append(rec)
    return out


FTM_RENAMES = {"proof": "sources"}               # standard FtM name -> hydra's (export writes them back)


def _props(d) -> dict:
    out: dict[str, list] = {}
    for p, v in (d or {}).items():
        out.setdefault(FTM_RENAMES.get(p, p), []).extend(str(x) for x in (v if isinstance(v, list) else [v]))
    return out


_SOURCE = re.compile(r"^([a-z0-9][a-z0-9._-]{0,63}):")
RESERVED_SOURCES = {"main", "session", "parsed", "manifest", "dynamic"}


def source_of(record_id) -> str | None:
    """The source an id names: the part before the first colon, if it is a
    valid, non-reserved source name. None for an unprefixed id."""
    m = _SOURCE.match(str(record_id or ""))
    return m.group(1) if m and m.group(1) not in RESERVED_SOURCES else None


# ---- prefixes ------------------------------------------------------------------

_SLUG = re.compile(r"[^a-z0-9._-]+")


def default_prefix(collection: str) -> str:
    """A prefix made from the collection name: `Fring Condensed` -> `fring-condensed`."""
    slug = _SLUG.sub("-", str(collection or "").lower()).strip("-._") or "collection"
    slug = slug[:64]
    return slug + "-c" if slug in RESERVED_SOURCES else slug


def valid_prefix(p) -> bool:
    return isinstance(p, str) and source_of(f"{p}:x") == p


def resolve_prefixes(collections, manifest: dict | None = None, archive: str | None = None) -> dict[str, str]:
    """{collection: prefix}: the manifest's choice, else the archive's prefix
    (`prefix:` in hydra.yaml), else one made from the collection's name."""
    declared = ((manifest or {}).get("collections") or {})
    fallback = archive if valid_prefix(archive) else None
    out = {}
    for c in sorted(set(collections)):
        t = (declared.get(c) or {}).get("prefix") if isinstance(declared.get(c), dict) else None
        out[c] = t if valid_prefix(t) else fallback or default_prefix(c)
    return out


def manifest_with_prefixes(manifest: dict | None, prefixes: dict[str, str]) -> dict:
    """A copy of the manifest with every collection's prefix stored in it."""
    out = {**(manifest or {})}
    cols = {k: dict(v) if isinstance(v, dict) else {} for k, v in (out.get("collections") or {}).items()}
    for c, t in prefixes.items():
        cols.setdefault(c, {})["prefix"] = t
    out["collections"] = cols
    return out


def link_ids(records: list[dict]) -> None:
    """Standard FtM writes a link as the id of the record it points at
    (`owner: ["NK-p1"]`); hydra writes the name (`owner: ["Ann Lee"]`). Each
    entity-typed value that is the id of a record in the archive is rewritten
    to that record's name, and the id is kept on the record (`_id_links`:
    {prop: {value: record id}}): the link resolvers follow the kept id, so the
    link is exact whatever the name, and an export can write the id back.
    A value stays an id when the record has no name, or when two records one
    field points at share a name (the name alone would not tell them apart)."""
    schema.ensure()
    by_id = {r["id"]: r for r in records if r.get("id")}
    for r in records:
        pdefs = schema.resolve(r["schema"])["props"] if r.get("schema") in schema.SCHEMA else {}
        links = {}
        for p, vals in (r.get("properties") or {}).items():
            if (pdefs.get(p) or {}).get("type") != "entity" or not any(v in by_id for v in vals):
                continue
            named = {v: ((by_id[v].get("properties") or {}).get("name") or [""])[0] for v in vals if v in by_id}
            taken = [n for n in named.values() if n]
            out, kept = [], {}
            for v in vals:
                n = named.get(v)
                if n and taken.count(n) == 1:
                    out.append(n)
                    kept[n] = v
                else:
                    out.append(v)
                    if v in by_id:
                        kept[v] = v
            r["properties"][p] = out
            links[p] = kept
        if links:
            r["_id_links"] = links


def prefixed_id(rid: str, prefix: str) -> str:
    return rid if source_of(rid) else f"{prefix}:{rid}"


def prefix_records(records: list[dict], manifest: dict | None = None,
                   archive: str | None = None) -> tuple[list[dict], dict]:
    """Records (each with `_collection`) -> (prefixed copies, report). The report
    carries `prefixes` {collection: prefix}, `manifest` (with prefixes stored),
    `collisions` (the same prefixed id produced by two different collections —
    two collections sharing a prefix and a local id), `ambiguous_pointers`, and
    `fallbacks`: collections that would take the archive's prefix but share a
    local id with one that already has it, so take their own instead (no record
    is lost to a duplicate id)."""
    prefixes = resolve_prefixes({r.get("_collection", "") for r in records}, manifest, archive)
    holders = defaultdict(set)                       # local id -> collections holding it
    for r in records:
        holders[r["id"]].add(r.get("_collection", ""))
    fallbacks = []
    if valid_prefix(archive):
        declared = ((manifest or {}).get("collections") or {})
        chosen = {c for c, v in declared.items() if isinstance(v, dict) and valid_prefix(v.get("prefix"))}
        local = defaultdict(set)
        for r in records:
            if not source_of(r["id"]):
                local[r.get("_collection", "")].add(r["id"])
        taken: dict[str, set] = defaultdict(set)     # prefix -> local ids already under it
        for c in sorted(prefixes):
            shared = local[c] & taken[prefixes[c]]
            if c not in chosen and prefixes[c] == archive and shared:
                prefixes[c] = default_prefix(c)
                fallbacks.append({"collection": c, "prefix": prefixes[c], "shared": len(shared)})
            taken[prefixes[c]] |= local[c]
    schema.ensure()
    out, seen, collisions, ambiguous = [], {}, [], []

    def point(v: str, coll: str, rid: str, prop: str) -> str:
        if source_of(v) or v not in holders:
            return v
        owners = holders[v]
        if coll in owners:
            return f"{prefixes[coll]}:{v}"
        if len(owners) == 1:
            return f"{prefixes[next(iter(owners))]}:{v}"
        ambiguous.append({"record": rid, "prop": prop, "value": v, "collections": sorted(owners)})
        return v

    for r in records:
        coll = r.get("_collection", "")
        prefix = prefixes[coll]
        props = {}
        pdefs = schema.resolve(r["schema"])["props"] if r.get("schema") in schema.SCHEMA else {}
        for p, vals in (r.get("properties") or {}).items():
            is_entity = (pdefs.get(p) or {}).get("type") == "entity"
            props[p] = [point(v, coll, r["id"], p) if is_entity else v for v in vals]
        nr = {**r, "id": prefixed_id(r["id"], prefix), "properties": props}
        if nr["id"] in seen and seen[nr["id"]] != coll:
            collisions.append({"id": nr["id"], "collections": sorted({seen[nr["id"]], coll})})
        seen.setdefault(nr["id"], coll)
        out.append(nr)
    return out, {"prefixes": prefixes, "manifest": manifest_with_prefixes(manifest, prefixes),
                 "collisions": collisions, "ambiguous_pointers": ambiguous, "fallbacks": fallbacks}
