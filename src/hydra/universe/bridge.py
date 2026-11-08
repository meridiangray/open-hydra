"""bridge.py — what the archive build takes from its universe layer, read only.

A decision keyed by a survivor id is lost when a richer record becomes the
survivor; keyed by an H it is not. So decisions may name Hs, and the archive
build turns them into the keys it has always read, for the records holding
those Hs now (from the last universe build). Nothing here writes a file.

    cap-H-<body>: Name               a caption pin on whichever record holds that H
    place-H-<child>-<parent>: ...    a placement decision between two Hs
    a row's `not: [body]`            its records and that H's are never merged (rejected)
"""
from __future__ import annotations

from collections import defaultdict

from hydra.review import ids
from hydra.universe import hid, layer, table

CAP_H = "cap-H-"
PLACE_H = "place-H-"


def place_key(child_body: str, parent_body: str) -> str:
    return f"{PLACE_H}{child_body}-{parent_body}"


def caption_key(body: str) -> str:
    return CAP_H + body


def records_by_body(root) -> dict[str, list[str]]:
    out = defaultdict(list)
    for rid, body in layer.h_of_records(root).items():
        out[body].append(rid)
    return out


def share_pins(root, records: list[dict]) -> list[dict]:
    """A record pinned `upstream: H-x` is one entity with the records holding H-x now: they
    are given the same pin, in memory, so the match sees one identifier on both sides
    (and a different pin on another record keeps it apart, as any identifier does).
    Likewise, when records carry `upstream` keys (`ns:key`) in a unique namespace that
    keys.yaml maps to an FtM property (`wikidataId`), records carrying that property
    receive the `ns:key` in `upstream` in memory so both forms match and conflict alike."""
    from hydra import keys as hkeys
    kconf = hkeys.load(root)
    prop_ns = {prop: ns for prop, ns in hkeys.by_property(kconf).items()
               if (kconf["namespaces"].get(ns) or {}).get("unique", True) is not False}
    pinned = set()
    for r in records:
        for v in (r.get("properties") or {}).get("upstream") or []:
            pk = hid.pin_key(v)
            if pk:
                pinned.add(pk[2:])
    holds = {rid: body for rid, body in layer.h_of_records(root).items() if body in pinned} \
        if (pinned and layer.is_universe(root)) else {}
    if not holds and not prop_ns:
        return records
    out = []
    for r in records:
        props = r.get("properties") or {}
        extra = []
        body = holds.get(r["id"])
        if body:
            existing_pks = {hid.pin_key(v) for v in props.get("upstream") or []}
            if "H-" + body not in existing_pks:
                extra.append("H-" + body)
        for prop, ns in prop_ns.items():
            for v in props.get(prop) or []:
                if str(v).strip():
                    k = f"{ns}:{hkeys.norm(kconf, ns, str(v))}"
                    if k not in (props.get("upstream") or []) and k not in extra:
                        extra.append(k)
        if extra:
            props = {**props, "upstream": [*(props.get("upstream") or []), *extra]}
            r = {**r, "properties": props}
        out.append(r)
    return out


def before_resolve(root, verdicts: dict) -> dict:
    """The verdicts the merge reads, with the universe's decisions on this archive's
    records added in memory: H caption pins and `not` lists. A decision the
    archive wrote itself is never overridden."""
    if not layer.is_universe(root):
        return verdicts
    by_body = records_by_body(root)
    if not by_body:
        return verdicts
    out = dict(verdicts)
    for k, v in verdicts.items():
        if isinstance(k, str) and k.startswith(CAP_H):
            for rid in by_body.get(k[len(CAP_H):], ()):
                out.setdefault(ids.caption_key(rid), v)
    rows = table.load(root)
    for body, row in rows.items():
        for other in row.get("not") or []:
            for a in by_body.get(body, ()):
                for b in by_body.get(table.follow(rows, other), ()):
                    out.setdefault(ids.merge_key(a, b), "rejected")
    return out


def after_resolve(root, verdicts: dict, survivors: dict, live_ids: set[str] | None = None) -> dict:
    """Placement decisions between Hs, as the survivor-keyed placement keys the reads use."""
    hs = [(k, v) for k, v in verdicts.items() if isinstance(k, str) and k.startswith(PLACE_H)]
    if not hs:
        return verdicts
    by_body = records_by_body(root)
    surv = lambda body: next((ids.survivor(survivors, r) for r in sorted(by_body.get(body, ()))
                              if live_ids is None or r in live_ids), None)
    out = dict(verdicts)
    for k, v in hs:
        child, _, parent = k[len(PLACE_H):].partition("-")
        sc, sp = surv(child), surv(parent)
        if sc and sp:
            out.setdefault(ids.place_key(sc, sp), v)
    return out


def node_body(root, node_id: str, stable: bool = True) -> str | None:
    """The H of a node of the last build (its id or any id merged into it). `stable`:
    only a published or decided H, which the H-table holds still; a computed H follows
    its records' ids (a prefix change gives it a new body), so a decision keyed by it
    would be lost where one keyed by a record id is kept."""
    from hydra import resources
    node = resources.declared_nodes(root).get(node_id) or {}
    hmap = layer.h_of_records(root) if layer.is_universe(root) else {}
    body = next((hmap[r] for r in (node_id, *(node.get("referents") or ())) if r in hmap), None)
    if body and stable and table.load(root).get(body, {}).get("state") not in ("p", "d"):
        return None
    return body


def placement_key(root, child: str, parent: str) -> str:
    """The key a placement decision is written under: by H when both nodes have a stable one."""
    bc, bp = node_body(root, child), node_body(root, parent)
    return place_key(bc, bp) if bc and bp else ids.place_key(child, parent)


def body_keys(root, survivors: dict, records) -> dict[str, str]:
    """{survivor id: H body} for the archive's entities (from the last universe build)."""
    hmap = layer.h_of_records(root) if layer.is_universe(root) else {}
    out = {}
    for rec in records:
        b = hmap.get(rec["id"])
        if b:
            out.setdefault(ids.survivor(survivors, rec["id"]), b)
    return out


def dead_keys(root, verdicts: dict) -> list[tuple[str, str]]:
    """H-keyed decisions naming no H of the last universe build: (key, why)."""
    if not any(isinstance(k, str) and k.startswith((CAP_H, PLACE_H)) for k in verdicts):
        return []
    known = set(records_by_body(root))
    out = []
    for k in verdicts:
        if isinstance(k, str) and k.startswith(CAP_H) and k[len(CAP_H):] not in known:
            out.append((k, "no record holds this H (build the universe, or the H is gone)"))
        elif isinstance(k, str) and k.startswith(PLACE_H):
            child, _, parent = k[len(PLACE_H):].partition("-")
            if child not in known or parent not in known:
                out.append((k, "no record holds one of these Hs"))
    return out
