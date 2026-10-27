"""Position-chain collapsing: a derived view on top of fold's placements.

`person -> Position -> ... -> organization` becomes one derived placement,
`person -> organization`, carrying the post's title. fold's own placements are
never changed: a Position stays a first-class record, and collapsing it is a
display choice. Only real `Position` records form chains; a plain `role:` is
already the title on its direct placement."""
from __future__ import annotations

from hydra import schema
from hydra.structure import fold as fold_mod
from hydra.structure.cycles import placement_label


def _is_position(schema_name: str) -> bool:
    return schema.is_a(schema_name, "Position")


def collapse_position_chains(records: list[dict], fold_result: dict,
                             cut: set | None = None) -> dict:
    """fold's result + the records -> {"derived_placements", "pid", "report"}.

    Each Position is resolved once (memoized depth-first walk, no depth cap) and
    every holder reuses the answer; edges in `cut` are never walked, and an edge
    back onto the current path is skipped and reported. `pid` here is the best
    container among a child's non-Position placements plus its derived ones. A
    child whose every chain dead-ends (a Position with no container) gets `None`:
    it stays a root, rather than showing a bare Position as its container."""
    placements = fold_result["placements"]
    cut = cut or set()
    schema_of = {r["id"]: r["schema"] for r in records}

    def is_pos(rid: str) -> bool:
        return _is_position(schema_of.get(rid, ""))

    def live(node: str) -> list[dict]:
        return [u for u in placements.get(node, [])
                if (node, u["container"], placement_label(u)) not in cut]

    folded_log: list[dict] = []
    cycle_skipped: list[dict] = []
    memo: dict[str, list[dict]] = {}

    def resolve(start: str) -> list[dict]:
        """Real (non-Position) placements `start` collapses to. Iterative
        post-order walk: a frame is [node, edges, next, acc, tainted]."""
        if start in memo:
            return memo[start]
        onpath = {start}
        stack = [[start, live(start), 0, [], False]]
        result: list[dict] = []
        while stack:
            fr = stack[-1]
            node, edges, i = fr[0], fr[1], fr[2]
            if i < len(edges):
                fr[2] += 1
                up = edges[i]
                c = up["container"]
                if not is_pos(c):
                    fr[3].append(up)
                elif c in onpath:
                    cycle_skipped.append({"post": node, "via": c})
                    fr[4] = True
                elif c in memo:
                    fr[3].extend(memo[c])
                else:
                    onpath.add(c)
                    stack.append([c, live(c), 0, [], False])
                continue
            stack.pop()
            onpath.discard(node)
            if not fr[4]:
                memo[node] = fr[3]
            result = fr[3]
            if stack:
                stack[-1][3].extend(fr[3])
                stack[-1][4] = stack[-1][4] or fr[4]
        return result

    derived: dict[str, list[dict]] = {}
    for child in sorted(placements):
        for p in placements[child]:
            if not is_pos(p["container"]):
                continue
            if (child, p["container"], placement_label(p)) in cut:
                continue
            for up in resolve(p["container"]):
                derived.setdefault(child, []).append({
                    **p, "container": up["container"], "role": up["role"],
                    "derived": True, "via_position": p["container"],
                })
                folded_log.append({"holder": child, "post": p["container"],
                                   "org": up["container"]})

    pid: dict[str, str | None] = {}
    for child, placed in placements.items():
        non_position = [p for p in placed
                        if not _is_position(schema_of.get(p["container"], ""))]
        had_position_routed = len(non_position) < len(placed)
        candidates = non_position + derived.get(child, [])
        if candidates:
            pid[child] = fold_mod.rank_placements(candidates)[0]["container"]
        elif had_position_routed:
            # every chain dead-ends at a Position with no container: a root
            pid[child] = None
        else:
            pid[child] = fold_result["pid"].get(child)  # nothing to collapse, unchanged

    return {"derived_placements": derived, "pid": pid,
            "report": {"folded": folded_log, "cycle_skipped": cycle_skipped}}
