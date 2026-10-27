"""Ties: every resolved link between two records, read once.

`reads.py` sorts them into relations (`rels`), sideways ties (`lateral`) and
evidence (`linked`). Two sources: an edge schema (source x target values, each
resolved against its own range) and an entity-typed property on any other
record. `Similar` records are skipped; merge owns them.

A value resolves by a `ref-` pin, then by the record id it was written as
(standard FtM links by id; `ingest.link_ids` turns those values into names and
keeps the ids), then by name (`match.resolve_reference`). An id that names a
record of the wrong type for the field is followed only for a document pointer
(a range in the Document family); anywhere else it is reported (`literal_ids`,
which lint turns into `records.literal-id` issues) and resolved by name like
any value. Ambiguous and unresolved values are reported, never guessed. Not ported from the old engine: edges stated through a reverse-named
property (`Person.directorshipDirector`)."""
from __future__ import annotations

from functools import partial

from hydra import dates, schema
from hydra.identity import match, merge as merge_mod
from hydra.review import ids, ledger as review, verdicts as vd


def scan(records: list[dict], merge_result: dict, schema_names: list[str],
         pins: dict | None = None, resolver=None) -> dict:
    pins = pins or {}
    survivors, indices = merge_result["survivors"], merge_result["indices"]
    by_id = {r["id"]: r for r in records}
    ambiguous: list[dict] = []
    unresolved: list[dict] = []
    literal: list[dict] = []

    find = partial(ids.survivor, survivors)

    def exists(rid: str) -> bool:
        return rid in by_id or any(rid in i.records for i in indices.values())

    refs: dict[tuple, set] = {}          # (entity, prop, text value) -> the record ids it resolved to

    def resolve(rec_id: str, prop: str, value: str, range_: str | None) -> str | None:
        rid = _resolve(rec_id, prop, value, range_)
        if rid:
            refs.setdefault((find(rec_id), prop, value), set()).add(rid)
        return rid

    def _resolve(rec_id: str, prop: str, value: str, range_: str | None) -> str | None:
        pin = vd.pin_target(pins, rec_id, prop, value, exists)
        if pin:
            return find(pin)
        hit = match.id_link(by_id.get(rec_id), prop, value, range_, indices)
        if hit:
            return find(hit)                           # a collection that follows ids
        if value in by_id:
            if review.is_provenance_pointer(range_):   # provenance pointers stay id-addressed
                return find(value)
            literal.append({"record": rec_id, "prop": prop, "value": value})
        if not range_:
            return None
        rid, how, cands = (resolver(value, range_) if resolver else
                           merge_mod.resolve_reference(value, range_, schema_names, indices))
        if rid:
            return find(rid)
        entry = {"record": rec_id, "prop": prop, "value": value}
        if how == "ambiguous":
            ambiguous.append({**entry, "candidates": cands})
        else:
            unresolved.append(entry)
        return None

    edges: list[dict] = []
    selfs: list[dict] = []       # both ends resolve to one entity: reported, never an edge
    for r in records:
        sname = r.get("schema")
        if sname not in schema.SCHEMA or schema.is_a(sname, "Similar"):
            continue
        props = r.get("properties") or {}
        pdefs = schema.resolve(sname)["props"]
        base = {"record": find(r["id"]), "schema": sname, "role": (props.get("role") or [""])[0],
                "relationship": (props.get("relationship") or [""])[0],    # Associate, Family: their wording, never a role
                "startDate": dates.earliest(props.get("startDate")) or "",
                "endDate": dates.latest(props.get("endDate")) or "",
                "date": (props.get("date") or [""])[0],
                "stale": bool(props.get("endDate"))}
        edge = schema.SCHEMA[sname].get("edge")
        if edge:
            sp, tp = edge["source"], edge["target"]
            for sv in props.get(sp) or []:
                s_id = resolve(r["id"], sp, sv, (pdefs.get(sp) or {}).get("range"))
                if not s_id:
                    continue
                for tv in props.get(tp) or []:
                    t_id = resolve(r["id"], tp, tv, (pdefs.get(tp) or {}).get("range"))
                    if t_id and t_id == s_id:
                        selfs.append({"record": r["id"], "schema": sname, "entity": s_id,
                                      "sp": sp, "a_value": sv, "tp": tp, "b_value": tv})
                    elif t_id:
                        edges.append({**base, "a": s_id, "b": t_id, "sp": sp, "tp": tp,
                                      "kind": "edge", "directed": edge.get("directed") is not False})
            continue
        me = find(r["id"])
        for p, vals in props.items():
            pd = pdefs.get(p) or {}
            if pd.get("type") != "entity":
                continue
            for v in vals:
                t_id = resolve(r["id"], p, v, pd.get("range"))
                if t_id and t_id == me:
                    selfs.append({"record": r["id"], "schema": sname, "entity": me,
                                  "sp": "", "a_value": None, "tp": p, "b_value": v})
                elif t_id:
                    edges.append({**base, "a": me, "b": t_id, "sp": "", "tp": p, "role": "", "relationship": "",
                                  "kind": "prop", "directed": True})
    at = lambda e: (e["record"], e["prop"], e["value"])
    return {"edges": edges, "refs": {k: sorted(v) for k, v in refs.items()}, "report": {"ambiguous": sorted(ambiguous, key=at),
                                       "unresolved": sorted(unresolved, key=at),
                                       "literal_ids": sorted(literal, key=at),
                                       "self_edges": sorted(selfs, key=lambda e: (
                                           e["record"], e["sp"], e["a_value"] or "", e["tp"], e["b_value"]))}}
