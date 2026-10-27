"""entities.py — the merged entities as FollowTheMoney JSON, links as record ids.

One entity per surviving record: `{id, schema, properties, referents, datasets}`.
`properties` is every value its merged records supplied (deduplicated, sorted).
With `links="ids"` (standard FtM) an entity-typed value (`member: ["Walter
White"]`) is written as the id of the record it resolved to, the way FtM tools
and the RDF model behind them expect; a value that resolved to nothing, or a
property the build does not resolve (an entity property of an edge schema other
than its two ends), stays as its text. With `links="names"` (hydra's dialect)
every value stays as the records wrote it, except a link to a document (Page,
Pages, Article...), which hydra itself follows by id: it is written as the id, so
the result goes back into a hydra collection with every link intact. `referents` lists the ids
merged into it, `datasets` the collections that supplied it. Not written by
the build: `export` computes it from the archive when asked."""
from __future__ import annotations

from functools import partial

from hydra import ingest, schema
from hydra.review import ids
from hydra.review.ledger import is_provenance_pointer


def entities(r, links: str = "ids") -> list[dict]:
    """`reads.Resolved` -> the merged entities, sorted by id."""
    find = partial(ids.survivor, r.survivors)
    refs = r.tscan.get("refs") or {}
    members: dict[str, set] = {}
    datasets: dict[str, set] = {}
    for rec in r.records:
        s = find(rec["id"])
        members.setdefault(s, set()).add(rec["id"])
        members[s].update(rec.get("_referents") or ())      # upstream merges, as written
        if rec.get("_collection"):
            datasets.setdefault(s, set()).add(rec["_collection"])
    out = []
    for rid in sorted(r.ents):
        rec = r.ents[rid]
        sname = rec.get("schema") or "Thing"
        pdefs = schema.resolve(sname)["props"] if sname in schema.SCHEMA else {}
        props = {}
        for p, vals in (rec.get("properties") or {}).items():
            pd = pdefs.get(p) or {}
            # an id where FtM wants one, and in hydra's dialect where hydra itself links by id (documents)
            linked = pd.get("type") == "entity" and (links == "ids" or is_provenance_pointer(pd.get("range")))
            got = {x for v in vals for x in (refs.get((rid, p, v)) or [v])} if linked else set(vals)
            got.discard("")
            if got:
                props[p] = sorted(got)
        if links == "ids":                             # standard FtM: its own property names
            for ftm, ours in ingest.FTM_RENAMES.items():
                if ours in props:
                    props[ftm] = props.pop(ours)
        ent = {"id": rid, "schema": sname, "properties": dict(sorted(props.items()))}
        merged = sorted(members.get(rid, set()) - {rid})
        if merged:
            ent["referents"] = merged
        ent["datasets"] = sorted(datasets.get(rid, set()))
        out.append(ent)
    return out
