"""collapse.py — position-chain collapsing, against the real demo corpus
plus synthetic cases for what the demo corpus doesn't happen to exercise
(a clean single-route collapse, a dead end, and a cycle).
"""
import json
from pathlib import Path


from hydra import schema  # noqa: E402
from hydra.identity import merge as m  # noqa: E402
from hydra.structure import collapse, fold  # noqa: E402

from _paths import HYDRA as ROOT  # noqa: E402
from _paths import DEMO as DEMO_DIR  # noqa: E402
TEMPLATE = ROOT / "src" / "hydra" / "template"
PARAMS = TEMPLATE / ".hydra" / "schema" / "params"
DIRECTION = TEMPLATE / ".hydra" / "schema" / "direction.yaml"
DEMO = DEMO_DIR


def _load():
    schema.load(root=str(TEMPLATE))


def _load_demo_records() -> list[dict]:
    records = []
    for f in sorted(DEMO.glob("*.json")):
        if f.name == "manifest.json":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for r in data:
                r = dict(r)
                r["_collection"] = f.stem
                records.append(r)
    return records


def _all_schemas():
    return sorted(schema.SCHEMA)


def _run_real():
    _load()
    records = _load_demo_records()
    direction = fold.load_direction(DIRECTION)
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    out = fold.fold(records, result, _all_schemas(), direction=direction, params_dir=PARAMS)
    return records, result, out, collapse.collapse_position_chains(records, out)


def _marty_id(result):
    return result["survivors"].get("sess-96cfcd44:p-marty", "sess-96cfcd44:p-marty")


# ---- the real case: Marty holds pos-head-security under org-fairbank ----------


def test_martys_occupancy_collapses_to_the_real_organization():
    _records, result, _out, col = _run_real()
    marty = _marty_id(result)
    derived = col["derived_placements"][marty]
    assert len(derived) == 1
    d = derived[0]
    assert d["container"] == "sess-96cfcd44:org-fairbank"
    assert d["role"] == "Head of Security"  # the Position's own title, reused
    assert d["via_position"] == "pos-head-security"
    assert d["derived"] is True
    assert d["schema"] == "Occupancy"  # the ORIGINAL relationship fact's schema, preserved


def test_folded_log_records_the_collapse_for_audit():
    _records, result, _out, col = _run_real()
    marty = _marty_id(result)
    assert {"holder": marty, "post": "pos-head-security",
            "org": "sess-96cfcd44:org-fairbank"} in col["report"]["folded"]


def test_fold_pys_own_pid_still_legitimately_points_at_the_position():
    """fold.py's own pid is a different, still-correct answer to a
    different question ("best-ranked real placement") -- collapsing doesn't
    retroactively make it wrong, it answers the DISPLAY question instead."""
    _records, result, out, _col = _run_real()
    marty = _marty_id(result)
    assert out["pid"][marty] == "pos-head-security"


def test_display_pid_never_points_at_a_bare_position():
    """The actual point of this module: a single-tree renderer must never
    be handed a Position as someone's primary container."""
    _records, result, _out, col = _run_real()
    marty = _marty_id(result)
    assert col["pid"][marty] != "pos-head-security"


def test_no_cycle_in_the_real_corpus():
    _records, _result, _out, col = _run_real()
    assert col["report"]["cycle_skipped"] == []


def test_a_child_with_no_position_routed_placement_is_unaffected():
    """Wallace Wright never holds a Position in this corpus -- his display
    pid must be identical to fold.py's own pid, untouched."""
    _records, _result, out, col = _run_real()
    assert col["pid"]["p-wal"] == out["pid"]["p-wal"]
    assert "p-wal" not in col["derived_placements"]


# ---- synthetic: a clean single-route collapse actually changes the pick --


def test_synthetic_person_whose_only_route_is_a_dead_end_becomes_a_root():
    """A Position with no placement of its own (nothing points it anywhere)
    -- the old engine's own documented behavior: "a post that reaches no
    container leaves its holder a root". Synthetic, since the demo corpus's
    one real Position always resolves."""
    _load()
    records = _load_demo_records()
    synthetic = [
        {"id": "pos-orphan", "schema": "Position", "_collection": "test",
         "properties": {"name": ["Orphan Post"]}},  # no `organization` at all
        {"id": "p-orphan-holder", "schema": "Person", "_collection": "test",
         "properties": {"name": ["Orphan Holder"]}},
        {"id": "rel-orphan", "schema": "Occupancy", "_collection": "test",
         "properties": {"holder": ["Orphan Holder"], "post": ["Orphan Post"]}},
    ]
    all_records = records + synthetic
    direction = fold.load_direction(DIRECTION)
    result = m.merge(all_records, _all_schemas(), params_dir=PARAMS)
    out = fold.fold(all_records, result, _all_schemas(), direction=direction, params_dir=PARAMS)
    col = collapse.collapse_position_chains(all_records, out)
    assert out["pid"]["p-orphan-holder"] == "pos-orphan"  # fold.py's own answer: the bare post
    assert col["pid"]["p-orphan-holder"] is None  # display: correctly a root, not the post
    assert "p-orphan-holder" not in col["derived_placements"]


def test_uncut_position_cycle_terminates_and_is_reported():
    """A genuine Position<->Position cycle CANNOT actually be constructed
    through the real merge/fold pipeline: `Position.organization`'s range is
    `Organization`, and `Position` never satisfies `is_a(..., "Organization")`
    -- confirmed directly before writing this test. So a Position's own
    container can structurally never be another Position via the normal
    route, and the depth cap this guards against is pure defense-in-depth,
    not a case the current schema set can produce. Tested directly against
    collapse_position_chains with a hand-built fold_result instead, which
    exercises the depth cap as a mechanism regardless of whether real data
    can currently trigger it."""
    _load()
    records = [
        {"id": "pos-a", "schema": "Position", "properties": {"name": ["Post A"]}},
        {"id": "pos-b", "schema": "Position", "properties": {"name": ["Post B"]}},
        {"id": "p-cycle", "schema": "Person", "properties": {"name": ["Cycle Holder"]}},
    ]
    empty_span = (None, None)
    entry = lambda sname, container, role: {
        "schema": sname, "collection": "test", "container": container, "role": role,
        "startDate": None, "endDate": None, "notes": None, "sources": None,
        "tier": "belonging", "_span": empty_span,
    }
    fold_result = {
        "placements": {
            "p-cycle": [entry("Occupancy", "pos-a", None)],
            "pos-a": [entry("Position", "pos-b", "Post A")],
            "pos-b": [entry("Position", "pos-a", "Post B")],
        },
        "pid": {"p-cycle": "pos-a", "pos-a": "pos-b", "pos-b": "pos-a"},
    }
    col = collapse.collapse_position_chains(records, fold_result)
    assert col["report"]["cycle_skipped"]  # terminated, not hung
    assert "p-cycle" not in col["derived_placements"]


def test_collapse_is_deterministic():
    records = _load_demo_records()
    _load()
    direction = fold.load_direction(DIRECTION)
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    out = fold.fold(records, result, _all_schemas(), direction=direction, params_dir=PARAMS)
    c1 = collapse.collapse_position_chains(records, out)
    c2 = collapse.collapse_position_chains(records, out)
    assert c1["pid"] == c2["pid"]
    assert c1["report"]["folded"] == c2["report"]["folded"]


def _entry(sname, container, role=None):
    return {"schema": sname, "collection": "test", "container": container, "role": role,
            "startDate": None, "endDate": None, "notes": None, "sources": None,
            "tier": "belonging", "_span": (None, None)}


def _recs(*pairs):
    return [{"id": i, "schema": s, "properties": {"name": [i]}} for i, s in pairs]


def test_shared_post_is_resolved_once_and_holders_do_not_share_dicts():
    _load()
    records = _recs(("org", "Organization"), ("post", "Position"),
                    ("h1", "Person"), ("h2", "Person"))
    fr = {"placements": {"h1": [_entry("Occupancy", "post", "A")],
                         "h2": [_entry("Occupancy", "post", "B")],
                         "post": [_entry("Position", "org", "Head")]}, "pid": {}}
    col = collapse.collapse_position_chains(records, fr)
    d1, d2 = col["derived_placements"]["h1"][0], col["derived_placements"]["h2"][0]
    assert d1["container"] == d2["container"] == "org"
    assert d1 is not d2 and d1["via_position"] == "post"


def test_long_chain_has_no_depth_cap():
    _load()
    n = 40
    records = _recs(("org", "Organization"), ("h", "Person"),
                    *[(f"p{i}", "Position") for i in range(n)])
    pl = {"h": [_entry("Occupancy", "p0")]}
    for i in range(n - 1):
        pl[f"p{i}"] = [_entry("Position", f"p{i+1}")]
    pl[f"p{n-1}"] = [_entry("Position", "org", "Head")]
    col = collapse.collapse_position_chains(records, {"placements": pl, "pid": {}})
    assert col["derived_placements"]["h"][0]["container"] == "org"
    assert col["report"]["cycle_skipped"] == []


def test_diamond_reaches_org_via_both_branches():
    _load()
    records = _recs(("org", "Organization"), ("h", "Person"), ("a", "Position"),
                    ("b", "Position"), ("top", "Position"))
    pl = {"h": [_entry("Occupancy", "a")],
          "a": [_entry("Position", "top"), _entry("Position", "b")],
          "b": [_entry("Position", "top")],
          "top": [_entry("Position", "org", "Head")]}
    col = collapse.collapse_position_chains(records, {"placements": pl, "pid": {}})
    assert {d["container"] for d in col["derived_placements"]["h"]} == {"org"}
    assert col["report"]["cycle_skipped"] == []


def test_cut_edge_breaks_a_position_loop_cleanly():
    _load()
    records = _recs(("org", "Organization"), ("h", "Person"),
                    ("a", "Position"), ("b", "Position"))
    pl = {"h": [_entry("Occupancy", "a")],
          "a": [_entry("Position", "b")],
          "b": [_entry("Position", "a"), _entry("Position", "org", "Head")]}
    cut = {("b", "a", "Position")}
    col = collapse.collapse_position_chains(records, {"placements": pl, "pid": {}}, cut=cut)
    assert [d["container"] for d in col["derived_placements"]["h"]] == ["org"]
    assert col["report"]["cycle_skipped"] == []
    col2 = collapse.collapse_position_chains(records, {"placements": pl, "pid": {}})
    assert col2["report"]["cycle_skipped"]  # no cut: guard fires, still terminates
    assert [d["container"] for d in col2["derived_placements"]["h"]] == ["org"]
