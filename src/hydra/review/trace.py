"""trace.py — why two records ended up as one entity, in values a person can check.

Evidence against a merge is only reported, never acted on: a `contradiction`
(a rejected sameAs that other links merged anyway) and a `selfEdge` (a link
whose two ends are one entity) leave the merge standing, so the person can fix
the data that caused it. Each such row carries `path`, the chain of merging
sameAs rows between the two records, and on every link `shared`, the values its
two sides have in common. A link with no shared values matched on values merged
in from other records, or was asserted (a `Similar` record, a confirm)."""
from __future__ import annotations

import hashlib
from collections import deque
from functools import partial

from hydra.identity import classify, types
from hydra.review import ids

MERGING = ("auto", "confirmed")


def link_graph(identical: list[dict]) -> dict[str, list[dict]]:
    """record id -> the merging sameAs rows that touch it, in id order."""
    g: dict[str, list[dict]] = {}
    for e in identical:
        if e.get("rel") == "sameAs" and e.get("status") in MERGING and e["a"] != e["b"]:
            g.setdefault(e["a"], []).append(e)
            g.setdefault(e["b"], []).append(e)
    for rows in g.values():
        rows.sort(key=lambda e: e["id"])
    return g


def path(graph: dict, a: str, b: str) -> list[dict] | None:
    """The fewest merging rows that chain `a` to `b` (ties: lowest row ids), or
    None when no chain of rows joins them."""
    if a == b:
        return []
    prev: dict[str, tuple[str, dict] | None] = {a: None}
    q = deque([a])
    while q:
        x = q.popleft()
        for e in graph.get(x, ()):
            y = e["b"] if e["a"] == x else e["a"]
            if y in prev:
                continue
            prev[y] = (x, e)
            if y == b:
                out = []
                while prev[y]:
                    y, e = prev[y]
                    out.append(e)
                return out[::-1]
            q.append(y)
    return None


def shared(ra: dict, rb: dict, params_dir=None) -> list[dict]:
    """The values two records match on: names pooled across their name fields,
    every other matching field compared with itself. `[{a_prop, a, b_prop, b, how}]`."""
    ca, cb = classify.classify(ra["schema"], params_dir), classify.classify(rb["schema"], params_dir)
    pa, pb = ra.get("properties") or {}, rb.get("properties") or {}
    out = []

    def names(c, p):
        return [(k, v) for k, pc in c.items() if pc.match and pc.ftm_type == "name"
                for v in p.get(k) or ()]
    for ka, va in names(ca, pa):
        for kb, vb in names(cb, pb):
            cmp = types.compare("name", va, vb)
            if cmp.signal is types.Signal.MATCH:
                out.append({"a_prop": ka, "a": va, "b_prop": kb, "b": vb, "how": cmp.how})
    for k, pc in ca.items():
        q = cb.get(k)
        if not (pc.match and q and q.match) or pc.ftm_type in ("name", "entity"):
            continue
        for va in pa.get(k) or ():
            for vb in pb.get(k) or ():
                cmp = types.compare(pc.ftm_type, va, vb)
                if cmp.signal is types.Signal.MATCH:
                    out.append({"a_prop": k, "a": va, "b_prop": k, "b": vb, "how": cmp.how})
    return out


def links(rows: list[dict], by_id: dict, params_dir=None) -> list[dict]:
    """A path as a person reads it: each link, why it merged, and on which values."""
    return [{"id": e["id"], "a": e["a"], "b": e["b"], "status": e["status"],
             "criteria": e.get("criteria", ""),
             "shared": shared(by_id[e["a"]], by_id[e["b"]], params_dir)
             if e["a"] in by_id and e["b"] in by_id else []}
            for e in rows]


def contradictions(identical: list[dict], survivors: dict, by_id: dict | None = None,
                   params_dir=None) -> list[dict]:
    """Rejected (NOT-sameAs) rows whose two ends nonetheless share a survivor
    because other confirmed/auto links chain them together. `conflicts` is where
    the two disagree, `path` how they were joined anyway."""
    by_id = by_id or {}
    shadowed = [e for e in identical if e.get("status") == "rejected"
                and ids.survivor(survivors, e["a"]) == ids.survivor(survivors, e["b"])]
    graph = link_graph(identical) if shadowed else {}     # built only when there is something to trace
    out = []
    for e in shadowed:
        chain = path(graph, e["a"], e["b"]) or []
        out.append({"id": ids.contradiction_key(e["id"]), "rel": "contradiction", "of": e["id"],
                    "a": e["a"], "b": e["b"], "status": "conflict",
                    "criteria": "rejected sameAs, but merged through other confirmed/auto links",
                    "conflicts": e.get("conflicts") or [],
                    "path": links(chain, by_id, params_dir),
                    "matcher": "hydra/review"})
    return out


def _named_by(value: str, members: list[str], by_id: dict, params_dir=None) -> list[str]:
    """Which of an entity's merged records a link's end names: its id, else an
    equal name, else a name of which it is a word subset (the resolver's rungs)."""
    if value in members:
        return [value]
    hits: dict[str, list[str]] = {"exact": [], "subset": []}
    for rid in members:
        rec = by_id.get(rid) or {}
        pcs = classify.classify(rec.get("schema") or "Thing", params_dir)
        props = rec.get("properties") or {}
        hows = {types.compare("name", value, v).how for k, pc in pcs.items()
                if pc.match and pc.ftm_type == "name" for v in props.get(k) or ()}
        for how in ("exact", "subset"):
            if how in hows:
                hits[how].append(rid)
                break
    return sorted(hits["exact"] or hits["subset"])


def self_edge_rows(self_edges: list[dict], identical: list[dict], survivors: dict,
                   by_id: dict, captions: dict | None = None, params_dir=None) -> list[dict]:
    """One row per link whose two ends resolve to one entity. When the ends name
    different merged records, `path` is the merge that made them one; when they
    name the same record, no merge is involved and `path` is empty."""
    if not self_edges:
        return []
    find = partial(ids.survivor, survivors)
    members: dict[str, list[str]] = {}
    for rid in sorted(by_id):
        members.setdefault(find(rid), []).append(rid)
    graph = link_graph(identical)
    out = []
    for s in self_edges:
        ent = s["entity"]
        ends = [{"prop": prop, "value": val,
                 "records": [s["record"]] if val is None else
                 _named_by(val, members.get(ent, [ent]), by_id, params_dir)}
                for prop, val in ((s["sp"], s["a_value"]), (s["tp"], s["b_value"]))]
        ra, rb = ends[0]["records"], ends[1]["records"]
        chain = None
        if ra and rb and not set(ra) & set(rb):
            for x in ra:
                for y in rb:
                    p = path(graph, x, y)
                    if p is not None and (chain is None or len(p) < len(chain)):
                        chain = p
        if chain:
            how = f"merged through {len(chain)} link(s)"
        elif ra and rb and set(ra) & set(rb):
            how = "both ends name the same record"
        else:
            how = "the merged records its ends name could not be told apart"
        key = "self-" + hashlib.sha256("\x1f".join(
            (s["record"], s["sp"], s["a_value"] or "", s["tp"], s["b_value"] or "")).encode()).hexdigest()[:16]
        out.append({"id": key, "rel": "selfEdge", "status": "conflict",
                    "record": find(s["record"]), "schema": s["schema"], "entity": ent,
                    "cap": (captions or {}).get(ent, ent), "ends": ends,
                    "criteria": f"both ends of one {s['schema']} are one entity: {how}",
                    "path": links(chain or [], by_id, params_dir),
                    "matcher": "hydra/review"})
    return sorted(out, key=lambda r: r["id"])
