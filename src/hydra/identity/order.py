"""Layer 3: the order classes are resolved in, from the `range` graph.

A class depends on the classes its match- or distinct-category entity
properties range over (after param files): those references must resolve
against already-merged records. Fold-only references (`Person.parent`) add no
dependency, because fold runs once after all merging. Classes are grouped into
waves by a topological sort of the strongly connected components; classes in
one wave do not depend on each other. Classes whose entity property ranges over
`Thing` (`Similar`, `Documentation`, `Sanction`, `CourtCaseParty`) land last.

A `range` always expands to every concrete schema that is-a that range; the
schema's `abstract` flag is not trusted. Deterministic: sorted names within a
wave."""
from __future__ import annotations

from pathlib import Path

from hydra import schema
from hydra.identity import classify


def concrete_classes_for_range(range_name: str, schema_universe: list[str]) -> set[str]:
    """The is-a closure of `range_name` within `schema_universe`, restricted
    to concrete (non-abstract) schemas — never gated on `schema.SCHEMA
    [range_name]["abstract"]` (see module docstring for why). Shared by
    class_graph() here and merge.py's cross-pass reference resolution, so
    there is exactly one place this expansion happens."""
    return {s for s in schema_universe if schema.is_a(s, range_name)
            and not schema.SCHEMA[s].get("abstract", False)}


def class_graph(schema_names: list[str], params_dir: str | Path | None = None) -> dict[str, set[str]]:
    """schema name -> set of classes it depends on: for every entity-typed
    property promoted to `match` or `distinct` (via classify.classify(),
    overrides applied), the full is-a closure of concrete schemas satisfying
    that property's `range`. A schema with no such property depends on
    nothing (empty set) and is eligible in the first pass."""
    graph: dict[str, set[str]] = {}
    for sname in schema_names:
        deps: set[str] = set()
        for prop, pc in classify.classify(sname, params_dir).items():
            if pc.ftm_type != "entity" or not pc.range or not (pc.match or pc.distinct):
                continue
            deps |= concrete_classes_for_range(pc.range, schema_names)
        graph[sname] = deps
    return graph


def tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    """Standard Tarjan's algorithm. `graph[x]` = nodes x depends on (points
    to). Returns strongly-connected components, each a list of node names;
    a node with no cycle is its own size-1 SCC."""
    index_counter = [0]
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    result: list[list[str]] = []

    def strongconnect(node: str) -> None:
        indices[node] = lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True
        for succ in graph.get(node, ()):
            if succ not in indices:
                strongconnect(succ)
                lowlink[node] = min(lowlink[node], lowlink[succ])
            elif on_stack.get(succ):
                lowlink[node] = min(lowlink[node], indices[succ])
        if lowlink[node] == indices[node]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == node:
                    break
            result.append(scc)

    for node in graph:
        if node not in indices:
            strongconnect(node)
    return result


def resolve_order(schema_names: list[str], params_dir: str | Path | None = None) -> list[list[str]]:
    """Topological sort of class_graph(), as a list of passes. Each pass is
    every class that becomes resolvable at the same wavefront — classes
    within one pass have no dependency relationship to each other (they may
    be mutually cyclic, resolved same-class-only, or simply independent).
    Deterministic: sorted class names within a pass; when multiple SCCs
    become ready in the same wavefront, they're merged into one pass rather
    than arbitrarily split."""
    return _wavefront_order(class_graph(schema_names, params_dir))


def _wavefront_order(graph: dict[str, set[str]]) -> list[list[str]]:
    """The pure graph algorithm behind resolve_order: SCC decomposition +
    topological wavefront grouping. Exposed separately from resolve_order so
    it's directly testable (including the cycle-handling path) without
    needing a real schema set or classify.py — class_graph() is the only
    thing that knows about schemas; this only knows about a dependency dict."""
    sccs = tarjan_scc(graph)
    scc_of = {n: i for i, scc in enumerate(sccs) for n in scc}
    scc_deps: dict[int, set[int]] = {i: set() for i in range(len(sccs))}
    for n, deps in graph.items():
        for d in deps:
            j = scc_of[d]
            if j != scc_of[n]:
                scc_deps[scc_of[n]].add(j)

    order: list[list[str]] = []
    resolved: set[int] = set()
    total = len(sccs)
    while len(resolved) < total:
        ready = [i for i in range(total) if i not in resolved and scc_deps[i] <= resolved]
        if not ready:
            raise RuntimeError("class_graph condensation is not a DAG — Tarjan/SCC bug")
        order.append(sorted(n for i in ready for n in sccs[i]))
        resolved.update(ready)
    return order
