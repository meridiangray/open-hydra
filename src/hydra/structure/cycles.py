"""Cycle map — every schema-possible containment cycle, derived from the
schema (never hardcoded by class or property name), categorized so a read
knows, per hop, whether it needs any cycle protection at all.

Inputs: `schema.SCHEMA` (type/range/edge) + `direction.yaml` (`above`/
`lateral`/`dual` — the same file fold.py reads, via `fold.infer_direction`).

**Hop families.** A *family* is one way a child points at a parent:
- an edge schema (`Membership`: child `member`, parent `organization`), or
- a direct entity-typed property whose NAME is in `above` on a non-edge
  schema (`Person.parent`, `Position.organization`).
Each family expands, via the is-a closure of its `range` (never gated on
`abstract`, see order.py), to a set of concrete child classes and a set of
concrete parent classes. An edge with BOTH ends ranging over `Thing`
(`Placement`, `UnknownLink`) is an unconstrained attach-to-anything link,
not a typed pathway, and is skipped — same treatment order.py gives it.
Lateral schemas never contain anything and are skipped.

**Pair tiers** (per `(child class, parent class, family)`):
- `dag`      — child and parent are in different class-graph SCCs: no
               cycle can run through this pair, ever, whatever the data.
- `direct`   — both classes can sit at BOTH ends of this same family
               (`Org --Directorship--> Org`): a one-hop loop.
- `indirect` — same SCC but not direct: only closes through other families
               (`Company --ContractAward--> Contract --authority--> Company`).

**Categories** (per family, from its pair tiers + overlap):
- `dag`         every pair is dag.
- `self_loop`   direct overlap is exactly one class (`CourtCase`,
                `RealEstate`, `Person.parent`'s Person→Person).
- `self_family` direct overlap spans several classes (`Directorship`'s
                Company/Organization/PublicBody).
Category describes the SHAPE of the cycle only. What type a dangling
endpoint could be is `stub_candidates[label][end]` — the classes at that
end, split into `cyclic` (inside a cyclic SCC) and `acyclic`. A one-class
end is determined (no verdict needed); `Person.parent` is a `self_loop`
yet its parent end is a five-way choice.
- `bridge`      only indirect pairs (`ContractAward`, `Employment`).

**Instance depth.** A family whose pairs are all `dag` terminates by schema
alone (depth is bounded by the class DAG's height). The schema cannot bound
INSTANCE depth inside a cyclic family (a chain of `Company.parent` is as long
as the data says), so this module never claims a depth cap for those; cycles in
the data are found once by `detect()` (below) and cut by evidence.

**Forms** (per pair, then per family). The three forms
describe how much of a relationship's direction is known:
- `dag`      vertical, direction authored, tier `dag`: positionality is
             resolved and a cycle is schema-impossible.
- `combined` vertical/direct-property family whose pair is cyclic (direction
             is authored but a loop can close), or a `dual` family.
- `ag`       authored lateral (`Debt`, `Payment`, `Family`...): no parent
             end, undirected; cycles are natural and never become the tree.
Lateral families are listed in `lateral`, never added to the class graph
(they contain nothing, so they cannot create a containment SCC).

Only cyclic families need instance-level protection; that is `detect()`, below."""
from __future__ import annotations

from dataclasses import dataclass

from hydra import dates, schema
from hydra.identity import order
from hydra.review import ids
from hydra.structure import fold as fold_mod


@dataclass(frozen=True)
class Family:
    label: str                 # "Membership" (edge) or "Person.parent" (prop)
    kind: str                  # "edge" | "prop"
    children: frozenset
    parents: frozenset
    direction: str = "vertical"  # authored: "vertical" | "dual"


def families(schema_names: list[str], fam: dict) -> list[Family]:
    above = set(fam.get("above") or [])
    out: list[Family] = []
    for sname in sorted(schema_names):
        sc = schema.SCHEMA[sname]
        if sc.get("abstract"):
            continue
        props = schema.resolve(sname)["props"]
        if sc.get("edge"):
            d = fold_mod.infer_direction(sname, fam)
            if d["kind"] not in ("vertical", "dual"):
                continue
            cr = props[d["child_prop"]].get("range")
            pr = props[d["parent_prop"]].get("range")
            if not cr or not pr or (cr == "Thing" and pr == "Thing"):
                continue
            out.append(Family(
                sname, "edge",
                frozenset(order.concrete_classes_for_range(cr, schema_names)),
                frozenset(order.concrete_classes_for_range(pr, schema_names)),
                d["kind"]))
        else:
            for pname in sorted(props):
                pd = props[pname]
                if pd.get("type") != "entity" or pname not in above or not pd.get("range"):
                    continue
                out.append(Family(
                    f"{sname}.{pname}", "prop", frozenset({sname}),
                    frozenset(order.concrete_classes_for_range(pd["range"], schema_names))))
    return out


def lateral_families(schema_names: list[str], fam: dict) -> list[Family]:
    """Authored-lateral edge schemas with typed ends (both ends `Thing` is
    unconstrained and skipped). Ends are source/target, undirected."""
    out: list[Family] = []
    for sname in sorted(schema_names):
        sc = schema.SCHEMA[sname]
        if sc.get("abstract") or not sc.get("edge"):
            continue
        if fold_mod.infer_direction(sname, fam)["kind"] != "lateral":
            continue
        props = schema.resolve(sname)["props"]
        sr = props[sc["edge"]["source"]].get("range")
        tr = props[sc["edge"]["target"]].get("range")
        if not sr or not tr or (sr == "Thing" and tr == "Thing"):
            continue
        out.append(Family(sname, "edge",
                          frozenset(order.concrete_classes_for_range(sr, schema_names)),
                          frozenset(order.concrete_classes_for_range(tr, schema_names)),
                          "lateral"))
    return out


def _class_graph(fams: list[Family]) -> dict[str, set[str]]:
    g: dict[str, set[str]] = {}
    for f in fams:
        for c in f.children:
            g.setdefault(c, set()).update(f.parents)
        for p in f.parents:
            g.setdefault(p, set())
    return g


def _cyclic_sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    return [sorted(s) for s in order.tarjan_scc(graph)
            if len(s) > 1 or s[0] in graph[s[0]]]


_CACHE: dict[tuple, dict] = {}


def cycle_map(schema_names: list[str], fam: dict) -> dict:
    """The schema-level cycle map, cached per loaded schema + families
    content (a build asks for it three times; it changes only with them)."""
    import json
    key = (schema.LOADED.get("key"), tuple(schema_names),
           json.dumps(fam or {}, sort_keys=True, default=sorted))
    if key[0] is not None and key in _CACHE:
        return _CACHE[key]
    out = _cycle_map(schema_names, fam)
    if key[0] is not None:
        _CACHE[key] = out
    return out


def _cycle_map(schema_names: list[str], fam: dict) -> dict:
    fams = families(schema_names, fam)
    sccs = _cyclic_sccs(_class_graph(fams))
    scc_of = {c: i for i, s in enumerate(sccs) for c in s}

    pairs: dict[str, dict[str, list[tuple[str, str]]]] = {}
    category: dict[str, str] = {}
    overlap: dict[str, list[str]] = {}
    for f in fams:
        ov = f.children & f.parents
        t: dict[str, list] = {"dag": [], "direct": [], "indirect": []}
        for c in sorted(f.children):
            for p in sorted(f.parents):
                if c in scc_of and scc_of.get(c) == scc_of.get(p):
                    t["direct" if (c in ov and p in ov) else "indirect"].append((c, p))
                else:
                    t["dag"].append((c, p))
        pairs[f.label] = t
        overlap[f.label] = sorted(ov)
        if not t["direct"] and not t["indirect"]:
            category[f.label] = "dag"
        elif not t["direct"]:
            category[f.label] = "bridge"
        else:
            category[f.label] = "self_loop" if len(ov) == 1 else "self_family"

    # forms: how much of the direction is known (see module docstring)
    pair_form: dict[str, dict[tuple[str, str], str]] = {}
    form: dict[str, str] = {}
    for f in fams:
        t = pairs[f.label]
        pf = {pr: "dag" for pr in t["dag"]}
        for pr in t["direct"] + t["indirect"]:
            pf[pr] = "combined"
        if f.direction == "dual":
            pf = {pr: "combined" for pr in pf}
        pair_form[f.label] = pf
        vals = set(pf.values())
        form[f.label] = ("dag" if vals == {"dag"} else
                         "combined")
    lat = lateral_families(schema_names, fam)
    for f in lat:
        form[f.label] = "ag"
    cyc = set(scc_of)
    stub_candidates = {
        f.label: {end: {"classes": sorted(cl),
                        "cyclic": sorted(cl & cyc), "acyclic": sorted(cl - cyc),
                        "determined": len(cl) == 1}
                  for end, cl in (("child", f.children), ("parent", f.parents))}
        for f in fams}
    return {
        "families": {f.label: f for f in fams},
        "sccs": sccs,
        "pairs": pairs,
        "category": category,
        "overlap": overlap,
        "stub_candidates": stub_candidates,
        "form": form,
        "pair_form": pair_form,
        "lateral": {f.label: f for f in lat},
    }


def sidecar(m: dict, fam: dict) -> dict:
    """Plain-data, deterministic form of the cycle map for `parsed.yaml`'s
    `relations` block: one entry per family (and per authored-lateral
    family). Derived — never authored, so it cannot drift from the schema."""
    governing = set(fam.get("governing") or [])
    out = {}
    for label, f in sorted(m["families"].items()):
        t = m["pairs"][label]
        entry = {
            "kind": f.kind, "direction": f.direction, "form": m["form"][label],
            "category": m["category"][label],
            "tier": "governing" if label in governing else "belonging",
            "children": sorted(f.children), "parents": sorted(f.parents),
            "pairs": {"dag": len(t["dag"]), "direct": len(t["direct"]),
                      "indirect": len(t["indirect"])},
        }
        out[label] = entry
    for label, f in sorted(m["lateral"].items()):
        out[label] = {"kind": f.kind, "direction": "lateral", "form": "ag",
                      "children": sorted(f.children), "parents": sorted(f.parents)}
    return {"families": out, "sccs": m["sccs"]}


# ---- instance level: pivot check + Tarjan over real placements --------------


def placement_label(p: dict) -> str:
    """The family label a fold placement belongs to: the edge schema, or
    `Schema.prop` for a direct-property fold."""
    return f"{p['schema']}.{p['via_prop']}" if p.get("via_prop") else p["schema"]


def _weakest(edge: dict) -> tuple:
    """Cut order: an ended edge goes before an active one, then the oldest
    (unknown start counts as oldest), then ids — the exact inverse of
    fold.rank_placements' "best placement" order, so what gets cut is what
    fold would have ranked lowest anyway."""
    return (0 if edge["endDate"] else 1, dates.key_start(edge["_span"]),
            edge["child"], edge["container"], edge["label"])


def detect(placements: dict[str, list[dict]], schema_of: dict[str, str], cmap: dict) -> dict:
    """fold's placements + the cycle map -> {"edges", "pivots", "cycles", "cut"}.

    1. Pivot check: an entity whose parents and children overlap closes a 1- or
       2-cycle there. Compared by resolved survivor id.
    2. Backstop: strongly connected components over the remaining non-`dag`
       edges (the schema proves a `dag` pair can never close a loop). Recursive:
       a single unbroken path of ~1000 non-dag hops would exceed Python's
       recursion limit; accepted, since hydra shapes data and does not store it.

    Each cyclic component gets an id (`ids.cycle_key`), and cut edges are chosen
    weakest-first (ended before active, then the oldest) until it is acyclic. A
    cut edge stays a real placement; it is only excluded from the primary-parent
    choice."""
    tier_of = {}
    for label, t in cmap["pairs"].items():
        for tier in ("dag", "direct", "indirect"):
            for c, p in t[tier]:
                tier_of[(label, c, p)] = tier
    edges = []
    for child in sorted(placements):
        for p in placements[child]:
            if p["container"] not in schema_of or child not in schema_of:
                continue
            label = placement_label(p)
            edges.append({"child": child, "container": p["container"], "label": label,
                          "endDate": p.get("endDate"), "_span": p["_span"],
                          "tier": tier_of.get((label, schema_of[child], schema_of[p["container"]])),
                          "form": cmap["pair_form"].get(label, {}).get(
                              (schema_of[child], schema_of[p["container"]])),
                          "cycle": None, "cut": False})

    parents: dict[str, dict[str, str]] = {}
    kids: dict[str, dict[str, str]] = {}
    for e in edges:
        parents.setdefault(e["child"], {}).setdefault(e["container"], e["label"])
        kids.setdefault(e["container"], {}).setdefault(e["child"], e["label"])
    pivots = []
    for x in sorted(set(parents) & set(kids)):
        for other in sorted(set(parents[x]) & set(kids[x])):
            pivots.append({"pivot": x, "other": other, "via": [kids[x][other], parents[x][other]]})

    def cyclic_sccs(edge_list):
        g: dict[str, set[str]] = {}
        for e in edge_list:
            g.setdefault(e["child"], set()).add(e["container"])
            g.setdefault(e["container"], set())
        return [sorted(s) for s in order.tarjan_scc(g) if len(s) > 1 or s[0] in g[s[0]]]

    cycles_out, cut = [], set()
    cyclable = [e for e in edges if e["tier"] != "dag"]   # unknown tier is kept
    for members in sorted(cyclic_sccs(cyclable)):
        mset = set(members)
        inside = [e for e in cyclable if e["child"] in mset and e["container"] in mset]
        cid = ids.cycle_key(members)
        for e in inside:
            e["cycle"] = cid
        live, cuts = list(inside), []
        while cyclic_sccs(live):
            live_sccs = cyclic_sccs(live)
            units: dict[tuple, list[dict]] = {}
            for e in live:
                if any(e["child"] in s and e["container"] in s for s in live_sccs):
                    units.setdefault((e["child"], e["container"]), []).append(e)
            # a direction (all parallel edges child->container) is cut as one
            # unit: its strongest edge speaks for it, fewer edges cut first
            victim = min(units.values(), key=lambda es: (
                max(_weakest(x)[:2] for x in es), len(es), min(_weakest(x) for x in es)))
            for e in victim:
                live.remove(e)
                e["cut"] = True
                cut.add((e["child"], e["container"], e["label"]))
                cuts.append({"child": e["child"], "container": e["container"],
                             "label": e["label"]})
        cycles_out.append({"id": cid, "members": members, "cut": cuts})
    return {"edges": edges, "pivots": pivots, "cycles": cycles_out, "cut": cut}
