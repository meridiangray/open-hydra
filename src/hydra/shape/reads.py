"""Shape the tree and emit a read: records -> the IR renderers
consume, `{read, roots, nodes, report, prop_types, ledger, rules}`.

Two stages. `resolve()` does everything the position rules don't touch (merge,
fold, ties, cycle detection, position-chain collapsing) and is shared by both
reads of a build. `build_reads()` then shapes one read in seven steps:

    1. primary parent per child (verdict veto/pin, ranked candidates)
    2. nodes                      5. kids, cycle cut, placement ledger rows
    3. positions, tier, badges    6. dashed ties for unapplied merge proposals
    4. rule placement in an org   7. ordering, report, emit
       (after 3b, hints.yaml overrides)

Every node keeps its survivor's own id and lists the merged-away ids in
`referents`. Cycle cut: each node has at most one primary parent, so the parent
map is a functional graph; a walk up either reaches a root or revisits a node
(`seen` is the guard). Nodes are visited in sorted-id order, so which edge is
cut is deterministic."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache, partial
from pathlib import Path

from hydra import schema
from hydra.common import (
    country_code, DEFAULT_HINTS, FORMER_PROPS, MEDIA_PROPS, orgish,
)
from hydra.dates import overlaps
from hydra.identity import classify, merge as merge_mod
from hydra.review import ids, ledger as review, trace, verdicts as vd
from hydra.shape.captions import caption
from hydra.shape.rules import (
    IMAGES, bad_patterns, canonical, closure, compile_rules, eval_hints, hint_match, rank_order, rule_set,
    inside_resources, rule_when, uses_titled,
)
from hydra.structure import (
    collapse as collapse_mod, cycles as cycles_mod, fold as fold_mod, ties as ties_mod,
)


def referents(survivors: dict, records, entity_ids) -> dict[str, list[str]]:
    """{entity id: sorted ids of every record merged into it (itself included), and
    the ids those records say an upstream tool merged into them (FtM `referents`,
    kept as written: they name records outside this archive)}."""
    find = partial(ids.survivor, survivors)
    out: dict[str, set] = {e: {e} for e in entity_ids}
    for rec in records:
        s = find(rec["id"])
        if s in out:
            out[s].add(rec["id"])
            out[s].update(rec.get("_referents") or ())
    return {e: sorted(v) for e, v in out.items()}


@dataclass
class Resolved:
    """What both reads share: computed once per build from records + verdicts."""
    m: dict                    # merge.merge()
    f: dict                    # fold.fold()
    survivors: dict
    ents: dict                 # survivor id -> merged record
    schema_of: dict
    cap: dict                  # survivor id -> caption
    is_pos: dict
    tscan: dict                # ties.scan()
    cyc: dict                  # cycles.detect()
    collapsed: dict            # collapse.collapse_position_chains()
    names: list
    records: list
    ref_rows: list = None      # references rows (with ranked candidates)
    contra: list = None        # contradiction rows
    selfs: list = None         # selfEdge rows: a link whose two ends are one entity



def resolve(records: list[dict], verdicts: dict | None = None, direction: dict | None = None,
            params_dir: str | Path | None = None) -> Resolved:
    """See `_resolve`; param files are read once for the whole pass."""
    with classify.frozen_params(params_dir):
        return _resolve(records, verdicts, direction, params_dir)


def _resolve(records: list[dict], verdicts: dict | None = None, direction: dict | None = None,
            params_dir: str | Path | None = None) -> Resolved:
    """Merge, fold, ties, cycles and collapsing: none of them read the position
    rules, so both reads of a build can share one result."""
    schema.ensure()
    direction = direction or fold_mod.load_direction(None)
    verdicts = verdicts or {}
    names = sorted(schema.SCHEMA)
    pins = vd.pins_from(verdicts)
    m = merge_mod.merge(records, names, params_dir=params_dir, verdicts=verdicts, pins=pins,
                        direction=direction)
    # merge's final indices no longer change: resolve each (value, range) once for fold and ties
    resolver = lru_cache(maxsize=None)(partial(_resolve_final, names, m["indices"]))
    f = fold_mod.fold(records, m, names, direction=direction, params_dir=params_dir, pins=pins,
                      resolver=resolver)
    survivors = m["survivors"]
    find = partial(ids.survivor, survivors)
    ents: dict[str, dict] = {}
    for idx in m["indices"].values():
        for rid, rec in idx.records.items():
            if find(rid) == rid:
                ents[rid] = rec
    for r in records:
        if find(r["id"]) == r["id"]:
            ents.setdefault(r["id"], r)
    schema_of = {rid: r["schema"] for rid, r in ents.items()}
    cyc = cycles_mod.detect(f["placements"], schema_of, cycles_mod.cycle_map(names, direction))
    tscan = ties_mod.scan(records, m, names, pins=pins, resolver=resolver)
    by_id = {r["id"]: r for r in records}
    cap = {rid: caption(r, verdicts) for rid, r in ents.items()}
    return Resolved(
        m=m, f=f, survivors=survivors, ents=ents, schema_of=schema_of,
        cap=cap,
        is_pos={rid: schema.is_a(s, "Position") for rid, s in schema_of.items()},
        tscan=tscan, cyc=cyc,
        collapsed=collapse_mod.collapse_position_chains(records, f, cut=cyc["cut"]),
        names=names, records=records,
        ref_rows=_reference_rows(m, f, tscan, records, names, verdicts),
        contra=review.contradictions(m["identical"], survivors, by_id, params_dir),
        selfs=trace.self_edge_rows(tscan["report"]["self_edges"], m["identical"], survivors,
                                   by_id, cap, params_dir))


def _resolve_final(names, indices, value, range_):
    return merge_mod.resolve_reference(value, range_, names, indices)


def _reference_rows(m, f, tscan, records, names, verdicts) -> list[dict]:
    """The `references` rows, with ranked candidates for a person to pick from."""
    entries = ([{**e, "kind": "ambiguous"} for e in m["report"]["ambiguous_references"]
                + f["report"]["ambiguous_endpoints"]]
               + [{**e, "kind": "unresolved"} for e in m["report"]["unresolved_references"]
                  + f["report"]["unresolved_endpoints"]]
               + [{**e, "kind": "ambiguous"} for e in tscan["report"]["ambiguous"]]
               + [{**e, "kind": "unresolved"} for e in tscan["report"]["unresolved"]])
    return review.reference_rows(
        entries, m["report"]["pinned_references"] + f["report"]["pinned_references"],
        m["indices"], {r["id"]: r["schema"] for r in records}, names, verdicts)


def build_reads(records: list[dict], rules: dict | None = None, verdicts: dict | None = None,
                read: str = "generic", overrides: dict | None = None,
                direction: dict | None = None, params_dir: str | Path | None = None,
                resolved: Resolved | None = None) -> dict:
    """One read. Pass `resolved` (from `resolve()` with the same records,
    verdicts and direction) to share the expensive stage between reads."""
    schema.ensure()
    direction = direction or fold_mod.load_direction(None)
    rules = rules or compile_rules(direction=direction)
    verdicts = verdicts or {}
    r = resolved or resolve(records, verdicts, direction, params_dir)
    positions = rules.get("positions") or {}
    excl = tuple((rules.get("model") or {}).get("exclude") or ())

    def renderable(rid: str) -> bool:
        s = r.schema_of.get(rid, "")
        return ((schema.is_a(s, "Thing") or s not in schema.SCHEMA)
                and not any(schema.is_a(s, x) for x in excl)
                and not r.is_pos.get(rid)
                and not (schema.SCHEMA.get(s) or {}).get("edge"))

    report: dict = {"cycles": {"cycles": r.cyc["cycles"], "pivots": r.cyc["pivots"],
                               "cut": sorted(r.cyc["cut"])}}
    lateral, rels, linked = _sort_ties(r, renderable, direction)
    parent, cand_all = _primary_parents(r, rules, positions, verdicts, report)
    nodes = _make_nodes(r, renderable, rules, lateral, rels, linked)
    _positions_and_badges(nodes, parent, cand_all, positions, r.schema_of)
    _apply_overrides(nodes, overrides, positions, report)
    _rule_placements(nodes, parent, rules, verdicts, r.schema_of)
    roots, placements = _attach(nodes, parent, verdicts, read, r.schema_of, report)
    _duplicates(nodes, r, report)
    return _emit(r, nodes, roots, placements, rules, positions, verdicts, read, report)


def _media(ents: dict, rid: str) -> str:
    props = (ents.get(rid) or {}).get("properties") or {}
    return next(((props.get(p) or [""])[0] for p in MEDIA_PROPS if (props.get(p) or [""])[0]), "")


def _sort_ties(r: Resolved, renderable, direction: dict):
    """Resolved links -> (lateral, rels, linked): a link between two drawn
    nodes is a relation (and maybe a sideways tie); one with only one drawn
    end is evidence linked to that end."""
    lat_schemas = set(direction.get("lateral") or ()) | {"Similar", "Placement"}
    above = set(direction.get("above") or ())
    cap, is_pos, schema_of = r.cap, r.is_pos, r.schema_of
    lateral: dict[str, list[dict]] = {}
    rels: dict[str, list[dict]] = {}
    linked: dict[str, list[dict]] = {}
    for e in r.tscan["edges"]:
        a, b = e["a"], e["b"]
        a_ok = renderable(a) or is_pos.get(a)
        b_ok = renderable(b) or is_pos.get(b)
        if not (a_ok and b_ok):
            if a_ok or b_ok:
                keep, other = (b, a) if b_ok else (a, b)
                linked.setdefault(keep, []).append(
                    {"schema": schema_of.get(other, ""), "id": other,
                     "caption": cap.get(other, other), "media": _media(r.ents, other) or None})
            continue

        def rel(other, mine, _e=e):
            return {"at": other, "cap": cap.get(other, other), "label": mine or "related",
                    "via": _e["schema"] if _e["kind"] != "prop" else _e["tp"],
                    "role": _e["role"], "relationship": _e["relationship"], "since": _e["startDate"] or _e["date"],
                    "until": _e["endDate"], "record": _e["record"], "stale": _e["stale"],
                    "pos": bool(is_pos.get(other))}

        def tie(_e=e, **extra):
            return {"to": b, "schema": _e["schema"], "prop": _e["tp"], "record": _e["record"],
                    "relationship": _e["relationship"], "to_caption": cap.get(b, b), **extra}

        if e["kind"] == "prop":
            rels.setdefault(a, []).append(rel(b, e["tp"]))
            rels.setdefault(b, []).append(rel(a, schema_of.get(a, "")))
            if e["tp"] not in above:
                lateral.setdefault(a, []).append(tie())
        else:
            rels.setdefault(a, []).append(rel(b, e["sp"]))
            rels.setdefault(b, []).append(rel(a, e["tp"]))
            kind = fold_mod.infer_direction(e["schema"], direction)["kind"]
            if kind in ("lateral", "dual", None) or not e["directed"] or e["schema"] in lat_schemas:
                lateral.setdefault(a, []).append(tie())
    # data order, not record order: parallel edges to one node sort by their record
    for v in rels.values():
        v.sort(key=lambda x: (x["cap"], x["at"], x["via"], x["label"], x["record"]))
    for v in lateral.values():
        v.sort(key=lambda x: (x["to_caption"], x["to"], x["schema"], x["prop"], x["record"]))
    for v in linked.values():
        v.sort(key=lambda x: (x["caption"], x["id"], x["schema"]))
    return lateral, rels, linked


def _primary_parents(r: Resolved, rules: dict, positions: dict, verdicts: dict, report: dict):
    """Step 1: candidates per child (real placements + position-collapsed ones,
    cut edges excluded), a verdict's veto or pin, then the ranked best."""
    f, c, cut, schema_of = r.f, r.collapsed, r.cyc["cut"], r.schema_of

    def candidates(child: str) -> list[dict]:
        out = [p for p in f["placements"].get(child, [])
               if not r.is_pos.get(p["container"])
               and (child, p["container"], cycles_mod.placement_label(p)) not in cut]
        derived = [p for p in c["derived_placements"].get(child, [])
                   if (child, p["via_position"], cycles_mod.placement_label(p)) not in cut]
        return out + derived

    report["folded"] = c["report"]["folded"]
    report["ambiguous"], report["sequential"] = [], []
    org_first = lambda cid: orgish(schema_of.get(cid, ""))
    _, below = closure(rules.get("edges") or [])
    role_power = lambda p: len(below.get(canonical(p.get("role") or "", positions) or "", ()))
    parent: dict[str, dict] = {}
    cand_all: dict[str, list[dict]] = {}
    for child in sorted(f["placements"]):
        cands = [p for p in candidates(child) if p["container"] in r.ents
                 and vd.status_of(verdicts, ids.place_key(child, p["container"])) != "rejected"]
        cand_all[child] = cands
        if not cands:
            continue
        pinned = [p for p in cands if vd.status_of(
            verdicts, ids.place_key(child, p["container"])) == "confirmed"]
        # a legal-entity container outranks a project/other one; loops are
        # already cut out of `cands`, so this never picks a cycle edge
        keep = (pinned and fold_mod.rank_placements(pinned, org_first, role_power)[0]) \
            or fold_mod.rank_placements(cands, org_first, role_power)[0]
        others = [p for p in cands if p["container"] != keep["container"]]
        alts = list(dict.fromkeys(p["container"] for p in others
                                  if overlaps(p["_span"], keep["_span"])))
        earlier = list(dict.fromkeys(p["container"] for p in others
                                     if not overlaps(p["_span"], keep["_span"])))
        # every edge record behind this parent (parallel edges, position chains),
        # so the tree traces back to claims.jsonl
        records = sorted({p["record"] for p in cands
                          if p["container"] == keep["container"] and p.get("record")})
        parent[child] = {"parent": keep["container"], "records": records,
                         "role": keep.get("role") or "",
                         "title": keep.get("role") or "", "via": keep["schema"],
                         "scope_via": keep.get("via_position") and keep["schema"],
                         "tier": keep.get("tier"), "conf": "fold" if keep.get("derived") else "edge",
                         "how": "id", "stale": False, "alts": alts}
        if alts:
            report["ambiguous"].append({"child": child, "kept": keep["container"], "alt": alts})
        if earlier:
            report["sequential"].append({"child": child, "kept": keep["container"], "other": earlier})
    return parent, cand_all


def _stated_titles(rec: dict, links: list, ents: dict) -> list[list[str]]:
    """The titles a record's own data states, as [field, value]: its
    `position`; the `role` on each relationship where it is FtM's edge source
    (member, employee, director, owner, holder, agent...), never the other end;
    and the name then aliases of each Position it holds, with or without an
    organization. Schema defaults (direction.yaml `edge_positions`) are not
    stated, so never count. What hints.yaml `titled:` matches."""
    out = [[f"{rec['schema']}.position", v] for v in (rec.get("properties") or {}).get("position") or []]
    for x in links:
        src = ((schema.SCHEMA.get(x.get("via") or "") or {}).get("edge") or {}).get("source")
        if x.get("role") and x.get("label") == src:
            out.append([f"{x['via']}.role", x["role"]])
        if x.get("via") == "Occupancy" and x.get("label") == "holder":
            post = (ents.get(x.get("at")) or {}).get("properties") or {}
            out += [["Position.name", v] for v in post.get("name") or []]
            out += [["Position.alias", v] for v in post.get("alias") or []]
    return [list(t) for t in dict.fromkeys(map(tuple, out))]


def _make_nodes(r: Resolved, renderable, rules: dict, lateral, rels, linked) -> dict:
    """Step 2: one node per drawn survivor. Its images and badges come only
    from rules (step 3), linked to it by its data; a record never names its
    own image."""
    nodes: dict[str, dict] = {}
    for rid, rec in r.ents.items():
        if not renderable(rid):
            continue
        props = rec.get("properties") or {}
        pdefs = schema.resolve(rec["schema"])["props"]
        links = list({(x["at"], x["label"], x["via"], x["record"]): x for x in rels.get(rid, [])}.values())
        flags = list(dict.fromkeys(f"flag-{country_code(v)}" for p, vals in props.items()
                                   if (pdefs.get(p) or {}).get("type") == "country"
                                   for v in vals if country_code(v)))
        nodes[rid] = {"id": rid, "schema": rec["schema"], "caption": r.cap[rid], "title": "",
                      "position": None, "positions": [], "tier": None, "outside": False,
                      "badge": None, "badges": [], **{f"{k}s": [] for k in IMAGES},
                      "stated_titles": _stated_titles(rec, links, r.ents),
                      "former": any(props.get(p) for p in FORMER_PROPS),
                      "props": props,
                      "linked": list({x["id"]: x for x in linked.get(rid, [])}.values()),
                      "fields": {p: v for p, v in props.items() if p in (rules.get("carry") or [])},
                      "notes": (props.get("notes") or [""])[0], "flags": flags,
                      "kids": [], "lateral": list(lateral.get(rid, [])), "pid": None, "alt": [],
                      "placement": None,
                      "rels": links}
    return nodes


def _positions_and_badges(nodes, parent, cand_all, positions, schema_of) -> None:
    """Step 3: each node's titles -> its position, tier, badges."""
    for rid, n in nodes.items():
        p = parent.get(rid) or {}
        pairs = ([p.get("title") or p.get("role")]
                 + [x.get("role") for x in cand_all.get(rid, [])]
                 + list(n["props"].get("position") or []))
        n["positions"] = list(dict.fromkeys(t for t in pairs if t))
        canon = next((canonical(t, positions) for t in n["positions"] if canonical(t, positions)), None)
        n["position"] = canon
        n["title"] = canon or (n["positions"][0] if n["positions"] else "")
        pd = positions.get(canon or "") or {}
        n["outside"] = bool(pd.get("outside"))
        if p and orgish(schema_of.get(p["parent"], "")) and schema.is_a(n["schema"], "Person"):
            n["tier"] = p.get("tier") or "belonging"
        extra = eval_hints(n["props"], n["schema"], DEFAULT_HINTS,
                           linked=n["linked"], position=n["position"])
        pool = extra + n["flags"]
        n["badges"] = ([n["badge"]] if n["badge"] else []) + \
                      [b for i, b in enumerate(pool) if b != n["badge"] and b not in pool[:i]]


def _apply_overrides(nodes, overrides, positions, report) -> None:
    """Step 3b: `.hydra/rules/hints.yaml` condition rules, in file order, never
    ids. Images add up: each `thumb`, `portrait` and `logo` a rule sets joins
    the node's list (`thumbs`, `portraits`, `logos`) as {path, rule, why},
    `why` being the [field, value] pairs that matched, so a view can cycle
    through them and say where each came from. The last `badge` set is the
    main one and the others stay in `badges`. A rule testing `titled` is
    display only: it never sets a position."""
    report["override_misses"] = [f"{k} (id-keyed entries are no longer read)"
                                 for k in (overrides or {}) if k != "hints"]
    for i, ov in enumerate((overrides or {}).get("hints") or []):
        when, eff = rule_when(ov), rule_set(ov)
        if not when or not eff:
            report["override_misses"].append(f"hints[{i}] (needs match: and set: position, badge, thumb, "
                                             "portrait or logo)")
            continue
        bad = bad_patterns(when)
        if bad:
            report["override_misses"].append(f"hints[{i}] (not a valid regular expression: {bad}; skipped)")
            continue
        for k in IMAGES:
            if eff.get(k) and not inside_resources(eff[k]):
                report["override_misses"].append(f"hints[{i}] ({k} '{eff[k]}' is outside .hydra/resources/; ignored)")
                eff = {x: v for x, v in eff.items() if x != k}
        if eff.get("position") and uses_titled(when):
            report["override_misses"].append(f"hints[{i}] (a `titled:` rule never sets a position; ignored)")
            eff = {k: v for k, v in eff.items() if k != "position"}
        hit = []
        for _, n in sorted(nodes.items()):
            why: list = []
            if hint_match(when, n["props"], n["schema"], n["linked"], n["position"], n["stated_titles"], why):
                hit.append((n, [list(t) for t in dict.fromkeys(map(tuple, why))]))
        if not hit:
            report["override_misses"].append(f"hints[{i}]")
        for n, why in hit:
            for k in IMAGES:
                if eff.get(k) and str(eff[k]) not in {x["path"] for x in n[f"{k}s"]}:
                    n[f"{k}s"].append({"path": str(eff[k]), "rule": i, "why": why})
            if eff.get("position"):
                canon = canonical(str(eff["position"]), positions) or str(eff["position"])
                n["position"], n["title"] = canon, canon
                n["outside"] = bool((positions.get(canon) or {}).get("outside"))
            if eff.get("badge"):
                n["badge"] = str(eff["badge"])
            n["badges"] = ([n["badge"]] if n["badge"] else []) + \
                          [b for b in n["badges"] if b != n["badge"]]


def _rule_placements(nodes, parent, rules, verdicts, schema_of) -> None:
    """Step 4: inside an organization, a positioned person goes under the
    nearest member holding a position above theirs (position rules only, no
    record linking the two). The search climbs to the organizations above,
    unless you confirmed the organization: then it stays inside it, and with
    no one there to go under, the person sits directly under it."""
    def org_chain(o):
        out, seen = [], set()
        while o and o not in seen and o in nodes:
            seen.add(o)
            if orgish(schema_of.get(o, "")):
                out.append(o)
            o = (parent.get(o) or {}).get("parent")
        return out

    members: dict[str, list[str]] = {}
    for rid, p in parent.items():
        if rid in nodes and nodes[rid]["position"]:
            members.setdefault(p["parent"], []).append(rid)
    ups: dict[str, list[str]] = {}
    for lo, up in rules.get("edges") or []:
        ups.setdefault(lo, []).append(up)
    rule_parent = {}
    for rid in sorted(nodes, key=lambda x: nodes[x]["caption"]):
        n, p = nodes[rid], parent.get(rid)
        if not n["position"] or n["outside"] or not p or not orgish(schema_of.get(p["parent"], "")):
            continue
        # the nearest level up that has a member wins; a confirmed parent at any
        # level is a pin and wins over it (captions only order the unconfirmed)
        status = lambda y: vd.status_of(verdicts, ids.place_key(rid, y))
        # an organization you confirmed bounds the search: inside it, never above it
        orgs = org_chain(p["parent"])[:1] if status(p["parent"]) == "confirmed" else org_chain(p["parent"])
        frontier, seen, hit, pinned = list(ups.get(n["position"], [])), set(), None, None
        while frontier and not pinned:
            level = set(frontier) - seen
            seen |= level
            for org in orgs:
                ys = sorted((y for y in members.get(org, [])
                             if y != rid and nodes[y]["position"] in level and status(y) != "rejected"),
                            key=lambda y: (status(y) != "confirmed", nodes[y]["caption"], y))
                if not ys:
                    continue
                if status(ys[0]) == "confirmed":
                    pinned = (ys[0], ys[1:], org)
                    break
                hit = hit or (ys[0], ys[1:], org)
            frontier = [u for q in level for u in ups.get(q, [])]
        hit = pinned or hit
        if hit:
            y, alts, org = hit
            rule_parent[rid] = {"parent": y, "records": [], "role": "", "conf": "rules", "via": "rules",
                                "how": "rules", "stale": False, "tier": None,
                                "rule": f"{n['position']} below {nodes[y]['position']}",
                                "org": org, "alts": alts}
    parent.update(rule_parent)


def _attach(nodes, parent, verdicts, read, schema_of, report):
    """Step 5: kids and roots, the cut of any remaining cycle, and one
    `placedUnder` ledger row per placed node."""
    report["cut"], roots, placements = [], [], []
    for rid in sorted(nodes):
        p = parent.get(rid)
        if not p or p["parent"] not in nodes:
            roots.append(rid)
            continue
        seen, cur, cyclic = {rid}, p["parent"], False
        while cur in parent and cur in nodes:
            if cur in seen:
                cyclic = True
                break
            seen.add(cur)
            cur = parent[cur]["parent"]
        if cyclic:
            report["cut"].append({"child": rid, "parent": p["parent"], "via": p["via"]})
            parent.pop(rid, None)
            roots.append(rid)
            continue
        nodes[p["parent"]]["kids"].append(rid)
        n = nodes[rid]
        n["pid"] = p["parent"]
        n["alt"] = [a for a in (p.get("alts") or []) if a in nodes]
        key = ids.place_key(rid, p["parent"])
        if p["conf"] == "rules":
            status, criteria = "proposed", f"rules: {p['rule']}"
        elif n["alt"]:
            status, criteria = "proposed", f"{p['via']} (several parents)"
        else:
            status, criteria = "auto", (f"{p['via']} via position" if p["conf"] == "fold" else p["via"])
        status = vd.status_of(verdicts, key) or status
        n["placement"] = {"status": status, "criteria": criteria, "ledger": key,
                          "records": p.get("records") or []}
        scope = p.get("org") or (p["parent"] if orgish(schema_of.get(p["parent"], "")) else "")
        placements.append({"id": key, "rel": "placedUnder", "sub": rid, "sup": p["parent"],
                           "subcap": n["caption"], "supcap": nodes[p["parent"]]["caption"],
                           "criteria": criteria, "status": status, "reads": [read],
                           "records": p.get("records") or [],
                           "scope": nodes[scope]["caption"] if scope in nodes else "",
                           "matcher": "hydra/hier"})
    return roots, placements


def _duplicates(nodes, r: Resolved, report) -> None:
    """Step 6: a dashed sideways tie for every merge still waiting on a person."""
    find = partial(ids.survivor, r.survivors)
    report["merged"] = sorted((e for e in r.m["identical"] if e["status"] in ("auto", "confirmed")),
                              key=lambda e: e["id"])
    report["duplicates"] = []
    for e in r.m["identical"]:
        if e["status"] not in ("proposed", "confirmed-stale"):
            continue
        a, b = find(e["a"]), find(e["b"])
        if a in nodes and b in nodes and a != b:
            nodes[a]["lateral"].append({"to": b, "schema": "Similar", "prop": "", "record": None,
                                        "to_caption": nodes[b]["caption"], "dup": True,
                                        "ledger": e["id"]})
            report["duplicates"].append({"a": a, "b": b, "criteria": e["criteria"],
                                         "ledger": e["id"]})


def _emit(r: Resolved, nodes, roots, placements, rules, positions, verdicts, read, report) -> dict:
    """Step 7: order kids and roots by the position graph, finish the report,
    and assemble the IR."""
    m, f, tscan = r.m, r.f, r.tscan
    ranked = lambda k: nodes[k]["position"] if nodes[k]["position"] in positions \
        and not nodes[k]["outside"] else None
    tie = lambda k: (ranked(k) is None, nodes[k]["tier"] != "governing", nodes[k]["caption"])
    for n in nodes.values():
        n["kids"] = rank_order(n["kids"], ranked, rules.get("edges") or [], tie)
    roots = rank_order(roots, ranked, rules.get("edges") or [], tie)
    report["ties"] = tscan["report"]
    report["provenance"] = {
        "sourced": sum(any(schema.is_a(x["schema"], "Document") or x["schema"] in ("Page", "Pages")
                            for x in n["linked"])
                        for n in nodes.values()),
        "total": len(nodes)}
    report["fold"] = f["report"]
    report["merge"] = m["report"]
    ref_rows, contra = r.ref_rows, r.contra
    report["reference_groups"] = review.reference_groups(ref_rows)
    report["contradictions"] = contra
    report["self_edges"] = r.selfs
    report["unrelated_titles"] = rules.get("unrelated") or []
    ptypes: dict[str, str] = {}
    for rec in r.ents.values():
        for p, pd in schema.resolve(rec["schema"])["props"].items():
            if pd.get("type"):
                ptypes.setdefault(p, pd["type"])
    refs = referents(r.survivors, r.records, r.ents)
    for rid, n in nodes.items():
        n["referents"] = refs[rid]
    return {"read": read, "roots": roots, "nodes": nodes, "report": report,
            "prop_types": ptypes, "ledger": m["identical"] + placements + ref_rows + contra + r.selfs,
            "claims": m["claims"],
            "rules": {"edges": rules.get("edges") or [],
                      "positions": {k: {"outside": v.get("outside"), "uppers": v.get("uppers")}
                                    for k, v in positions.items()}}}


def diff_reads(a: dict, b: dict) -> dict:
    """What read b (declared) changed relative to read a (generic only)."""
    moved, added = [], []
    for rid, nb in b["nodes"].items():
        na = a["nodes"].get(rid)
        if na and na.get("pid") != nb.get("pid"):
            moved.append({"node": rid, "caption": nb["caption"],
                          "from": (a["nodes"].get(na.get("pid") or "") or {}).get("caption"),
                          "to": (b["nodes"].get(nb.get("pid") or "") or {}).get("caption")})
        if nb.get("position") and not (na or {}).get("position"):
            added.append({"node": rid, "caption": nb["caption"], "position": nb["position"]})
    return {"moved": moved, "newly_positioned": added}
