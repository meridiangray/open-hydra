"""Layer 3 (order.py) tests. Two groups, deliberately kept separate:

1. Pure graph algorithm (tarjan_scc, _wavefront_order) against small,
   hand-built synthetic graphs — including a deliberate cycle, since the
   real schema data does not exercise that path (checked empirically
   below) and the algorithm still has to be correct when it does.
2. class_graph/resolve_order against the real, fully-loaded 72-schema set
   with real param files — not just Person/Organization/Membership.
"""
from pathlib import Path


from hydra import schema  # noqa: E402
from hydra.identity import order  # noqa: E402

from _paths import HYDRA as ROOT  # noqa: E402
TEMPLATE = ROOT / "src" / "hydra" / "template"
PARAMS = TEMPLATE / ".hydra" / "schema" / "params"


def _load():
    schema.load(root=str(TEMPLATE))


# ---- pure graph algorithm: synthetic graphs --------------------------------


def test_tarjan_no_cycle_is_all_singletons():
    graph = {"A": {"B"}, "B": {"C"}, "C": set()}
    sccs = order.tarjan_scc(graph)
    assert sorted(sorted(s) for s in sccs) == [["A"], ["B"], ["C"]]


def test_tarjan_finds_a_genuine_mutual_cycle():
    """A depends on B and C; B depends back on A (mutual cycle); C is
    independent. {A,B} must land in one SCC, {C} in its own."""
    graph = {"A": {"B", "C"}, "B": {"A"}, "C": set()}
    sccs = order.tarjan_scc(graph)
    as_sets = [set(s) for s in sccs]
    assert {"A", "B"} in as_sets
    assert {"C"} in as_sets
    assert len(sccs) == 2


def test_wavefront_order_respects_dependency_direction():
    """C has no deps (pass 0); B depends on C (pass 1); A depends on B
    (pass 2). A linear chain, not a diamond -- each its own pass."""
    graph = {"A": {"B"}, "B": {"C"}, "C": set()}
    passes = order._wavefront_order(graph)
    assert passes == [["C"], ["B"], ["A"]]


def test_wavefront_order_groups_independent_nodes_in_one_pass():
    """X and Y both depend only on Z (no dependency between X and Y
    themselves) -- they must land in the SAME pass, not be arbitrarily
    split into two."""
    graph = {"Z": set(), "X": {"Z"}, "Y": {"Z"}}
    passes = order._wavefront_order(graph)
    assert passes == [["Z"], ["X", "Y"]]


def test_wavefront_order_places_a_mutual_cycle_as_one_pass_after_its_deps():
    """A<->B mutual cycle, both also depending on C. C resolves first;
    {A,B} resolve together as one pass, since neither can precede the
    other, only sorted alphabetically within that pass."""
    graph = {"A": {"B", "C"}, "B": {"A", "C"}, "C": set()}
    passes = order._wavefront_order(graph)
    assert passes == [["C"], ["A", "B"]]


def test_wavefront_order_is_deterministic():
    graph = {"A": {"B", "C"}, "B": {"A"}, "C": set(), "D": set()}
    assert order._wavefront_order(graph) == order._wavefront_order(graph)


# ---- class_graph / resolve_order against the real, full schema set --------


def test_position_depends_on_organization_family():
    """The motivating case: Position.organization is promoted to `distinct`
    by Position.param.yaml, so Position must resolve after Organization
    and its concrete subclasses (Company, PublicBody)."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    graph = order.class_graph(all_schemas, params_dir=PARAMS)
    assert graph["Position"] == {"Organization", "Company", "PublicBody"}


def test_membership_depends_on_legal_entity_and_organization_families():
    _load()
    all_schemas = sorted(schema.SCHEMA)
    graph = order.class_graph(all_schemas, params_dir=PARAMS)
    assert graph["Membership"] == {"Person", "Organization", "Company", "PublicBody", "LegalEntity"}


def test_fold_only_self_reference_creates_no_dependency():
    """Person.parent and Organization.parent stay fold-only in the real
    param files (never promoted to match/distinct) -- confirming they do
    NOT chain Person/Organization into a dependency on themselves or each
    other via the shared LegalEntity range."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    graph = order.class_graph(all_schemas, params_dir=PARAMS)
    assert graph["Person"] == set()
    assert graph["Organization"] == set()


def test_wide_thing_range_schemas_resolve_last():
    """Similar/Documentation/Sanction/CourtCaseParty promote an endpoint
    ranging over `Thing` (40 concrete classes) -- they must land in the
    final pass, after every class they could possibly attach to."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    passes = order.resolve_order(all_schemas, params_dir=PARAMS)
    last_pass = set(passes[-1])
    for s in ("Similar", "Documentation", "Sanction", "CourtCaseParty"):
        assert s in last_pass, f"{s} not in final pass: {passes.index([p for p in passes if s in p][0])}"


def test_real_data_has_no_genuine_cycle():
    """Documents an empirical fact about the CURRENT real data, not a
    property the algorithm requires — if a future param.yaml edit
    introduces a genuine cycle (e.g. promoting Organization.parent to
    `distinct`), this test should start failing, and that's a signal to
    re-verify the change was intentional, not evidence of a bug here."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    graph = order.class_graph(all_schemas, params_dir=PARAMS)
    sccs = order.tarjan_scc(graph)
    cycles = [s for s in sccs if len(s) > 1]
    assert cycles == [], f"unexpected genuine cycle(s) in real data: {cycles}"


def test_resolve_order_covers_every_loaded_schema_exactly_once():
    """Full-surface check: every one of the 72 loaded schemas appears in
    exactly one pass, none dropped, none duplicated."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    passes = order.resolve_order(all_schemas, params_dir=PARAMS)
    flat = [n for p in passes for n in p]
    assert sorted(flat) == all_schemas
    assert len(flat) == len(set(flat))


def test_resolve_order_runs_clean_with_no_param_files_at_all():
    """Acceptance test in the same spirit as Layer 2's: must not crash for
    schemas with no param.yaml (params_dir=None -> every entity-typed prop
    is fold-only by default, so the graph degenerates to all-independent,
    one pass -- which is itself a useful property to pin down)."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    passes = order.resolve_order(all_schemas, params_dir=None)
    assert len(passes) == 1
    assert sorted(passes[0]) == all_schemas
