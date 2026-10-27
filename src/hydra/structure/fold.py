"""Layer 5: placements, from `direction.yaml`.

Which end of an edge is the parent comes from `direction.yaml`'s `above` names
(target first, then source); the schema cannot say it. Two forms fold:

- an edge schema (Membership, Employment, Directorship, Occupancy, Ownership,
  ProjectParticipant, ContractAward...): child end under parent end, titled by
  the record's `role` or the schema's `edge_positions` default;
- a non-edge record's own entity property named in `above` (Position.
  organization, BankAccount.bank, Vehicle.owner and .operator): the record
  under the value, titled by its own fold-category title field, else the
  property name.

Every placement is kept (a record with five containers has five); `pid` is a
single-tree convenience ranked by `rank_placements()`: active before ended,
then the most recent start, then container id. Lateral schemas produce no
placement. Position chains are collapsed later, in collapse.py."""
from __future__ import annotations

from functools import partial

from pathlib import Path


from hydra import dates, schema, yamlcache
from hydra.identity import classify, match, merge as merge_mod
from hydra.review import ids, verdicts as vd

_DEFAULT_DIRECTION = {"above": [], "lateral": [], "dual": [], "governing": [], "edge_positions": {},
                     "exclude": []}


def load_direction(direction_path: str | Path | None) -> dict:
    """Read direction.yaml if given; an empty-but-well-formed dict otherwise
    (nothing vertical resolves, everything is an unclassified gap — same
    "correct from defaults alone" spirit as classify.py's acceptance test,
    just with an honestly empty default rather than a guessed one)."""
    if not direction_path:
        return dict(_DEFAULT_DIRECTION)
    doc = yamlcache.load(direction_path) or {}
    return {
        "above": doc.get("above") or [], "lateral": doc.get("lateral") or [],
        "dual": doc.get("dual") or [], "governing": doc.get("governing") or [],
        "edge_positions": doc.get("edge_positions") or {},
        "exclude": doc.get("exclude") or [],
    }


def infer_direction(schema_name: str, direction: dict) -> dict:
    """-> {kind: "vertical"|"dual", parent_prop, child_prop}
       | {kind: "lateral"}
       | {kind: None}   (unclassified — a direction.yaml gap, reported by
                         fold(), never silently treated as lateral)
    `kind: None` also covers every non-edge schema — a schema with no
    `schema.SCHEMA[...]["edge"]` has no single "direction" (it may have
    several independent entity-typed properties, each its own candidate —
    that's the deferred direct-property-fold case, handled per-property by
    a later version of fold(), not here)."""
    above = set(direction.get("above") or [])
    lateral = set(direction.get("lateral") or [])
    dual = set(direction.get("dual") or [])
    edge = (schema.SCHEMA.get(schema_name) or {}).get("edge")

    if schema_name in lateral and schema_name not in dual:
        return {"kind": "lateral"}
    if not edge:
        return {"kind": None}

    src, tgt = edge.get("source"), edge.get("target")
    if tgt in above:
        parent_prop, child_prop = tgt, src
    elif src in above:
        parent_prop, child_prop = src, tgt
    elif schema_name in lateral:
        return {"kind": "lateral"}
    else:
        return {"kind": None}

    return {"kind": "dual" if schema_name in dual else "vertical",
            "parent_prop": parent_prop, "child_prop": child_prop}


def _first(props: dict, key: str):
    return (props.get(key) or [None])[0]


def _all(props: dict, key: str) -> list[str]:
    return sorted({v for v in props.get(key) or () if v})


def _identity(p: dict) -> tuple:
    """What tells two placements of one child apart, data only: parallel edges
    to one container differ by record, a record's two direct folds by prop."""
    return (p["container"], p.get("record") or "", p.get("via_prop") or "", p["schema"],
            p.get("collection") or "")


def rank_placements(placed: list[dict], prefer=None, power=None) -> list[dict]:
    """A child's own placement list, ranked best-first by the same rule
    fold()'s `pid` pick uses: the optional `prefer(container_id) -> bool`
    (preferred containers first), then active (no `endDate`) beats ended,
    then the optional `power(placement) -> number` (higher first — a role
    higher in the position graph), most-recent-start wins among ties, container id breaks any remaining
    tie, then the edge record (never file order). Public and reusable — collapse.py's display-pid computation needs
    the exact same ordering over a different (derived) candidate set, and
    duplicating the sort would risk the two silently drifting apart."""
    ordered = sorted(placed, key=_identity)
    ordered = sorted(ordered, key=lambda p: dates.key_start(p["_span"]), reverse=True)
    if power:
        ordered = sorted(ordered, key=lambda p: -power(p))
    ordered = sorted(ordered, key=lambda p: bool(p["endDate"]))
    if prefer:
        ordered = sorted(ordered, key=lambda p: not prefer(p["container"]))
    return ordered


def _title_source_props(prop_classes: dict) -> list[str]:
    """This schema's own fold-category, NON-entity-typed properties — the
    title/role source for a direct-property fold (`Position.name`,
    `Person.position`/`title`). Order follows `schema.resolve()`'s own
    iteration (FTM's declaration order), not necessarily param.yaml's
    authored `fold:` list order — a known, minor imprecision, not claimed
    as exact when both a schema's `position` and `title` are populated."""
    return [p for p, pc in prop_classes.items() if pc.fold and pc.ftm_type != "entity"]


def _own_title(record: dict, title_props: list[str]) -> str | None:
    props = record.get("properties") or {}
    for p in title_props:
        vals = props.get(p) or []
        if vals:
            return vals[0]
    return None



def fold(records: list[dict], merge_result: dict, schema_names: list[str],
         direction: dict | None = None, params_dir: str | Path | None = None,
         pins: dict | None = None, resolver=None) -> dict:
    """See `_fold`; param files are read once for the whole pass. `resolver(value,
    range)` may be shared with ties.scan(): both resolve against merge's final indices."""
    with classify.frozen_params(params_dir):
        return _fold(records, merge_result, schema_names, direction=direction, params_dir=params_dir,
                     pins=pins, resolver=resolver)


def _fold(records: list[dict], merge_result: dict, schema_names: list[str],
         direction: dict | None = None, params_dir: str | Path | None = None,
         pins: dict | None = None, resolver=None) -> dict:
    """merge.merge()'s full result + the same raw records -> {
        "placements": {survivor_id: [ {schema, collection, container, record,
                                       via_prop, role, startDate, endDate,
                                       notes, sources, tier}, ... ]},
        "pid": {survivor_id: primary_container_survivor_id},
        "report": {"unclassified_schemas": [...], "unresolved_endpoints": [...]},
    }
    Every placement kept — a record with 5 real containers keeps 5 entries,
    never collapsed to one; parallel edges to one container stay one entry
    each, told apart by `record`: the edge record's surviving id (the
    `entity` its values carry in claims.jsonl), or the record itself for a
    direct-property fold. Two duplicates of one edge merged into one survivor
    keep one placement per collection. `startDate` / `endDate` are the earliest
    start and latest end over all values (the bounds `_span` uses); `notes` /
    `sources` keep every value, sorted. Each list is in `_identity` order, so a
    rebuild never depends on record order. `pid` is a single-tree convenience derived from
    the same list, not a second source of truth. `params_dir` is needed
    here (unlike edge-schema folding) to find a direct-property fold's own
    title source via classify.py's fold category."""
    direction = direction or dict(_DEFAULT_DIRECTION)
    survivors = merge_result["survivors"]
    indices = merge_result["indices"]
    above = set(direction.get("above") or [])
    pins = pins or {}
    pinned: list[dict] = []

    def _exists(rid: str) -> bool:
        return rid in survivors or any(rid in i.records for i in indices.values())

    find = partial(ids.survivor, survivors)   # a merged-away id -> the id that kept it

    placements: dict[str, list[dict]] = {}
    unclassified: set[str] = set()
    ambiguous: list[dict] = []
    unresolved: list[dict] = []

    by_id = {r["id"]: r for r in records}

    def resolve(record_id: str, prop_name: str, value: str, range_: str | None) -> str | None:
        """-> resolved record id, or None (and a report entry filed under
        `ambiguous` or `unresolved` -- kept distinct, not flattened into one
        generic bucket, because they mean different things to a reviewer:
        "pick one of these" vs. "nothing here at all")."""
        if not range_:
            return None
        pin = vd.pin_target(pins, record_id, prop_name, value, _exists)
        if pin:
            pinned.append({"record": record_id, "prop": prop_name, "value": value, "pinned": pin})
            return pin
        hit = match.id_link(by_id.get(record_id), prop_name, value, range_, indices)
        if hit:
            return hit
        rid, how, candidates = (resolver(value, range_) if resolver else
                                merge_mod.resolve_reference(value, range_, schema_names, indices))
        if rid:
            return rid
        entry = {"record": record_id, "prop": prop_name, "value": value}
        if how == "ambiguous":
            ambiguous.append({**entry, "candidates": candidates})
        else:
            unresolved.append(entry)
        return None

    def place(child: str, parent: str, sname: str, collection: str, record: str,
              role: str | None, props: dict, prop: str | None = None) -> None:
        tier = "governing" if sname in (direction.get("governing") or []) else "belonging"
        placements.setdefault(child, []).append({
            "schema": sname, "collection": collection, "container": parent,
            "record": record, "via_prop": prop,
            "role": role, "startDate": dates.earliest(props.get("startDate")),
            "endDate": dates.latest(props.get("endDate")), "notes": _all(props, "notes"),
            "sources": _all(props, "sources"), "tier": tier,
            "_span": dates.span(props.get("startDate"), props.get("endDate")),
        })

    for r in records:
        sname = r.get("schema")
        if sname not in schema_names:
            continue
        way = infer_direction(sname, direction)       # this edge's: vertical, lateral, dual or unknown
        kind = way.get("kind")
        if kind == "lateral":
            continue
        if kind is None:
            if (schema.SCHEMA.get(sname) or {}).get("edge"):
                unclassified.add(sname)  # real edge schema, no direction.yaml entry
                continue
            # non-edge schema: each of its OWN entity-typed properties named
            # in `above` is an independent direct-property fold candidate
            # (Vehicle has both `owner` and `operator` — two placements)
            prop_classes = classify.classify(sname, params_dir)
            title_props = _title_source_props(prop_classes)
            title = _own_title(r, title_props)
            props = r.get("properties") or {}
            collection = r.get("_collection", "unknown")
            for prop, pc in prop_classes.items():
                if pc.ftm_type != "entity" or prop not in above:
                    continue
                for v in props.get(prop) or []:
                    resolved = resolve(r["id"], prop, v, pc.range)
                    if not resolved:
                        continue
                    place(find(r["id"]), find(resolved), sname, collection, find(r["id"]),
                          title or prop, props, prop=prop)
            continue

        parent_prop, child_prop = way["parent_prop"], way["child_prop"]
        props = r.get("properties") or {}
        pdefs = schema.resolve(sname)["props"]
        parent_range = (pdefs.get(parent_prop) or {}).get("range")
        child_range = (pdefs.get(child_prop) or {}).get("range")
        role = _first(props, "role") or (direction.get("edge_positions") or {}).get(sname)
        collection = r.get("_collection", "unknown")

        for pv in props.get(parent_prop) or []:
            presolved = resolve(r["id"], parent_prop, pv, parent_range)
            if not presolved:
                continue
            for cv in props.get(child_prop) or []:
                cresolved = resolve(r["id"], child_prop, cv, child_range)
                if not cresolved:
                    continue
                place(find(cresolved), find(presolved), sname, collection, find(r["id"]),
                      role, props)

    for placed in placements.values():
        placed.sort(key=_identity)

    pid: dict[str, str] = {}
    ambiguous_primary: list[dict] = []
    sequential_primary: list[dict] = []
    for child, placed in sorted(placements.items()):
        ordered = rank_placements(placed)
        chosen = ordered[0]
        pid[child] = chosen["container"]

        alts = [p for p in ordered[1:] if p["container"] != chosen["container"]]
        overlapping = list(dict.fromkeys(
            p["container"] for p in alts if dates.overlaps(p["_span"], chosen["_span"])))
        disjoint = list(dict.fromkeys(
            p["container"] for p in alts if not dates.overlaps(p["_span"], chosen["_span"])))
        if overlapping:
            ambiguous_primary.append({"child": child, "chosen": chosen["container"],
                                      "alternatives": overlapping})
        if disjoint:
            sequential_primary.append({"child": child, "chosen": chosen["container"],
                                       "earlier_or_later": disjoint})

    at = lambda e: (e["record"], e["prop"], e["value"])
    return {"placements": placements, "pid": pid,
            "report": {"unclassified_schemas": sorted(unclassified),
                       "ambiguous_endpoints": sorted(ambiguous, key=at),
                       "unresolved_endpoints": sorted(unresolved, key=at),
                       "pinned_references": sorted(pinned, key=at),
                       "ambiguous_primary": ambiguous_primary,
                       "sequential_primary": sequential_primary}}
