"""Scope — which organizations an entity is directly attached to — used to
decide whether two exact-name records are the same person.

Old engine rule, kept: same exact name + shared scope -> auto; neither has a
scope -> auto; both have scopes but none shared -> proposed; only one has a
scope -> proposed. What is new is that scope evidence has a STRENGTH, and
only a firm one may support an automatic merge:

  firm       the organization resolved to exactly one settled container
  cyclic     the container sits in a membership cycle among containers; the
             whole component counts as ONE scope (which member is "the"
             organization is not well defined inside a loop)
  ambiguous  the organization value matches several containers
  phantom    the organization value matches none (a dangling stub)

Unsettled evidence (anything but firm) can only produce `proposed`. Two
guarantees keep this from becoming circular: scope reads DIRECT containers
only — never an organization's own `parent`, which may point back at a
Person — and the container relation is derived from `direction.yaml` + the
schema (vertical edge families whose parent end is Organization-only), not
from names."""
from __future__ import annotations

from collections import defaultdict

from hydra import schema
from hydra.identity import match, order, types


def scope_families(fam: dict, schema_names: list[str]) -> list[dict]:
    """Vertical edge schemas whose parent end ranges ONLY over Organization
    descendants (Membership, Directorship, Employment): the relations that
    mean "attached to an organization"."""
    from hydra.structure import fold as fold_mod
    out = []
    for sname in sorted(schema_names):
        sc = schema.SCHEMA[sname]
        if sc.get("abstract") or not sc.get("edge"):
            continue
        d = fold_mod.infer_direction(sname, fam)
        if d["kind"] != "vertical":
            continue
        props = schema.resolve(sname)["props"]
        pr = props[d["parent_prop"]].get("range")
        cr = props[d["child_prop"]].get("range")
        if not pr or not cr:
            continue
        parents = order.concrete_classes_for_range(pr, schema_names)
        if parents and all(schema.is_a(p, "Organization") for p in parents):
            out.append({"schema": sname, "child_prop": d["child_prop"],
                        "parent_prop": d["parent_prop"], "parent_range": pr,
                        "child_range": cr, "parents": parents})
    return out


def container_classes(sfams: list[dict]) -> set[str]:
    return set().union(*[f["parents"] for f in sfams]) if sfams else set()


def _norm_values(rec: dict, pcs: dict) -> set[str]:
    out = set()
    for prop, vals in (rec.get("properties") or {}).items():
        pc = pcs.get(prop)
        if pc and pc.match and pc.ftm_type in types.TOKEN_TYPES:
            out |= {types.norm_text(v) for v in vals if types.norm_text(v)}
    return out


def compute_scopes(records: list[dict], sfams: list[dict], bearing: set[str],
                   pcs_by_schema: dict, indices: dict, schema_names: list[str],
                   resolve_reference, find) -> dict[str, list[tuple[str, str]]]:
    """record id -> sorted [(scope key, kind)] for every scope-bearing record.
    `indices` must already hold the settled container classes; `find` maps a
    record id to its current survivor."""
    by_coll: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    ids_by_coll: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r["schema"] in bearing:
            coll = r.get("_collection", "unknown")
            ids_by_coll[coll].add(r["id"])
            for n in _norm_values(r, pcs_by_schema.get(r["schema"], {})):
                by_coll[coll][n].append(r["id"])

    def local_child(coll: str, value: str) -> str | None:
        if value in ids_by_coll[coll]:
            return value
        hits = sorted(set(by_coll[coll].get(types.norm_text(value), [])))
        return hits[0] if len(hits) == 1 else None

    edges: list[tuple[str, str, str]] = []      # (child record, scope key, kind-ish)
    org_edges: dict[str, set[str]] = defaultdict(set)    # container -> containers it sits in
    for r in records:
        for f in sfams:
            if r["schema"] != f["schema"]:
                continue
            props = r.get("properties") or {}
            coll = r.get("_collection", "unknown")
            for pv in props.get(f["parent_prop"]) or []:
                hit = match.id_link(r, f["parent_prop"], pv, f["parent_range"], indices)
                pid, how, _c = (hit, "id", [hit]) if hit else resolve_reference(pv, f["parent_range"], schema_names, indices)
                if pid:
                    pkey, kind = find(pid), "firm"
                elif how == "ambiguous":
                    pkey, kind = "ambiguous:" + types.norm_text(pv), "ambiguous"
                else:
                    pkey, kind = "phantom:" + types.norm_text(pv), "phantom"
                for cv in props.get(f["child_prop"]) or []:
                    child = local_child(coll, cv)
                    if child:
                        edges.append((child, pkey, kind))
                    hit = match.id_link(r, f["child_prop"], cv, f["child_range"], indices)
                    cid, _h, _cc = (hit, "id", [hit]) if hit else resolve_reference(cv, f["child_range"], schema_names, indices)
                    if cid and kind == "firm" and schema.is_a(
                            next((i.records[cid]["schema"] for i in indices.values() if cid in i.records),
                                 ""), "Organization"):
                        org_edges[find(cid)].add(pkey)

    graph = {n: set() for n in set(org_edges) | {t for v in org_edges.values() for t in v}}
    for a, ts in org_edges.items():
        graph[a] |= ts
    comp_of = {}
    for scc in order.tarjan_scc(graph):
        if len(scc) > 1 or scc[0] in graph[scc[0]]:
            for n in scc:
                comp_of[n] = "cyc:" + min(scc)

    scopes: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for child, pkey, kind in edges:
        if kind == "firm" and pkey in comp_of:
            scopes[child].add((comp_of[pkey], "cyclic"))
        else:
            scopes[child].add((pkey, kind))
    return {rid: sorted(v) for rid, v in scopes.items()}


def decide(scope_a: list, scope_b: list) -> tuple[str, str, str]:
    """Two exact-name, no-conflict records -> (status, criteria, scope_basis)."""
    if not scope_a and not scope_b:
        return "auto", "same name", "none"
    if bool(scope_a) != bool(scope_b):
        return "proposed", "same name, one has no org", "one-sided"
    ka, kb = dict(scope_a), dict(scope_b)
    shared = set(ka) & set(kb)
    if any(ka[k] == "firm" and kb[k] == "firm" for k in shared):
        return "auto", "same name, shared scope", "firm"
    if shared:
        kinds = sorted({ka[k] for k in shared} | {kb[k] for k in shared})
        return "proposed", f"same name, shared scope is unsettled ({'/'.join(kinds)})", "unsettled"
    return "proposed", "same name, different scope", "different"
