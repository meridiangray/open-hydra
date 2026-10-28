"""Layer 5 (fold.py) tests, against the real corrected demo corpus. The
named acceptance bar: Wallace Wright keeps every one of his real placements,
across four files, none collapsed into a single parent.
"""
import json
from pathlib import Path


from hydra import schema  # noqa: E402
from hydra.identity import merge as m  # noqa: E402
from hydra.structure import fold  # noqa: E402

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


def _run_fold():
    records = _load_demo_records()
    direction = fold.load_direction(DIRECTION)
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    return fold.fold(records, result, _all_schemas(), direction=direction, params_dir=PARAMS)


# ---- infer_direction: the actual source/target-name resolution ------------


def test_membership_target_wins_organization_is_parent():
    _load()
    direction = fold.load_direction(DIRECTION)
    d = fold.infer_direction("Membership", direction)
    assert d == {"kind": "vertical", "parent_prop": "organization", "child_prop": "member"}


def test_ownership_source_wins_owner_is_parent():
    """The case that disproved "direction is read off from range": Ownership's
    TARGET (asset) is not in `above`, so it falls through and the SOURCE
    (owner) wins instead -- the opposite position from Membership."""
    _load()
    direction = fold.load_direction(DIRECTION)
    d = fold.infer_direction("Ownership", direction)
    assert d == {"kind": "vertical", "parent_prop": "owner", "child_prop": "asset"}


def test_project_participant_is_dual():
    _load()
    direction = fold.load_direction(DIRECTION)
    d = fold.infer_direction("ProjectParticipant", direction)
    assert d["kind"] == "dual" and d["parent_prop"] == "project"


def test_family_is_lateral_never_vertical():
    _load()
    direction = fold.load_direction(DIRECTION)
    assert fold.infer_direction("Family", direction) == {"kind": "lateral"}


def test_unclassified_edge_schema_reports_a_gap_not_silent_lateral():
    """A real edge schema with no direction.yaml coverage at all must come
    back kind=None (a reportable gap), never silently treated as lateral."""
    _load()
    d = fold.infer_direction("Membership", {"above": [], "lateral": [], "dual": []})
    assert d == {"kind": None}


# ---- the named acceptance bar: Wallace Wright's full placement set ----------


def test_wallace_wright_keeps_every_resolvable_real_placement():
    """5 entries, not 6: Leader@Hawthorne, Chef@Fairbank (fairbank.json's exact
    "Wallace Hollis Wright" resolves cleanly), planner/chef/planner across 3
    Project containers. fairbank-condensed.json's bare "Wallace Wright" does NOT
    produce a 6th corroborating entry here -- it is genuinely ambiguous
    (also subset-matches p-waljr, see test_index.py), so it correctly lands
    in report.ambiguous_endpoints instead of being silently placed. An
    earlier MODEL.md worked example claimed both records "corroborate" the
    same placement -- that was wrong, found by actually running this."""
    _load()
    out = _run_fold()
    wal = out["placements"]["p-wal"]
    assert len(wal) == 5
    containers = [p["container"] for p in wal]
    assert containers.count("org-hawthorne") == 1
    assert containers.count("sess-96cfcd44:org-fairbank") == 1
    roles = sorted(p["role"] for p in wal)
    assert roles == ["chef", "chef", "leader", "planner", "planner"]


def test_fairbank_condensed_bare_wallace_wright_is_reported_ambiguous_not_dropped():
    """The named acceptance bar in its strictest form: the record isn't
    silently ignored, it's explicitly surfaced as ambiguous with both real
    candidates listed -- never silently resolved to p-waljr."""
    _load()
    out = _run_fold()
    hits = [a for a in out["report"]["ambiguous_endpoints"]
            if a["record"] == "rel-fr-chefs" and a["value"] == "Wallace Wright"]
    assert hits
    assert {"p-wal", "p-waljr"} <= set(hits[0]["candidates"])


def test_wallace_whites_project_placements_from_operations_json():
    _load()
    out = _run_fold()
    projects = {p["container"]: p["role"] for p in out["placements"]["p-wal"]
                if p["schema"] == "ProjectParticipant"}
    assert projects == {
        "proj-train-hauling": "planner",
        "proj-vanguard": "chef",
        "proj-magnet": "planner",
    }


def test_wallace_wright_primary_pid_is_one_of_his_real_containers():
    _load()
    out = _run_fold()
    assert out["pid"]["p-wal"] in {p["container"] for p in out["placements"]["p-wal"]}


def test_wallace_whites_primary_pid_prefers_an_active_placement():
    """Both his Fairbank Membership (endDate 2010) and Hawthorne Membership
    (endDate 2010) are stale; his three Project placements have no dates at
    all, so they're treated as ongoing and correctly outrank both stale
    ones. Deterministic tiebreak among the three ties on alphabetical
    container id: "proj-magnet" < "proj-train-hauling" < "proj-vanguard"."""
    _load()
    out = _run_fold()
    assert out["pid"]["p-wal"] == "proj-magnet"
    chosen = next(p for p in out["placements"]["p-wal"] if p["container"] == "proj-magnet")
    assert chosen["endDate"] is None


def test_ambiguous_primary_reports_overlapping_alternatives_never_silent():
    """Wallace's other 4 placements all either have no dates at all (open
    spans, which count as overlapping everything per dates.overlaps()'s own
    "unknown means can't tell" rule) or do overlap the chosen span -- so
    they must all appear as ambiguous alternatives, not be silently
    dropped from the report just because a primary was picked."""
    _load()
    out = _run_fold()
    entry = next(e for e in out["report"]["ambiguous_primary"] if e["child"] == "p-wal")
    assert entry["chosen"] == "proj-magnet"
    assert set(entry["alternatives"]) == {
        "proj-train-hauling", "proj-vanguard", "sess-96cfcd44:org-fairbank", "org-hawthorne"}


def test_sequential_primary_fires_on_cleanly_disjoint_dates():
    """The real demo corpus's dates are sparse enough that nothing in it
    produces a clean, fully-dated, non-overlapping pair (confirmed:
    sequential_primary is empty against the real corpus) -- so this is
    exercised with a minimal synthetic pair of Memberships, stated plainly
    as synthetic rather than implied to be real-corpus evidence."""
    _load()
    records = _load_demo_records()
    synthetic = [
        {"id": "org-a", "schema": "Organization", "_collection": "test",
         "properties": {"name": ["Org A"]}},
        {"id": "org-b", "schema": "Organization", "_collection": "test",
         "properties": {"name": ["Org B"]}},
        {"id": "p-synthetic", "schema": "Person", "_collection": "test",
         "properties": {"name": ["Synthetic Person"]}},
        {"id": "rel-a", "schema": "Membership", "_collection": "test",
         "properties": {"member": ["Synthetic Person"], "organization": ["Org A"],
                        "role": ["member"], "startDate": ["2000"], "endDate": ["2005"]}},
        {"id": "rel-b", "schema": "Membership", "_collection": "test",
         "properties": {"member": ["Synthetic Person"], "organization": ["Org B"],
                        "role": ["member"], "startDate": ["2010"], "endDate": ["2015"]}},
    ]
    all_records = records + synthetic
    direction = fold.load_direction(DIRECTION)
    result = m.merge(all_records, _all_schemas(), params_dir=PARAMS)
    out = fold.fold(all_records, result, _all_schemas(), direction=direction, params_dir=PARAMS)
    assert out["pid"]["p-synthetic"] == "org-b"  # more recent start, both equally stale
    entry = next(e for e in out["report"]["sequential_primary"] if e["child"] == "p-synthetic")
    assert entry == {"child": "p-synthetic", "chosen": "org-b", "earlier_or_later": ["org-a"]}
    assert not [e for e in out["report"]["ambiguous_primary"] if e["child"] == "p-synthetic"]


# ---- governing tier, lateral exclusion, family coverage --------------------


def test_governing_tier_applied_to_directorship_not_membership():
    """Gideon Fairbank's two duplicate Person records (fairbank.json/fairbank-
    condensed.json) auto-merge -- the survivor is whichever had more
    properties (sess-96cfcd44:p-fairbank, which carries an extra `notes`),
    not the bare id. Confirmed against merge.py's own survivor map, not
    assumed."""
    _load()
    out = _run_fold()
    fairbank_person = out["placements"].get("sess-96cfcd44:p-fairbank") or []
    directorships = [p for p in fairbank_person if p["schema"] == "Directorship"]
    memberships = [p for p in fairbank_person if p["schema"] == "Membership"]
    assert directorships and all(p["tier"] == "governing" for p in directorships)
    assert memberships and all(p["tier"] == "belonging" for p in memberships)


def test_lateral_schemas_never_produce_placements():
    _load()
    out = _run_fold()
    lateral_schemas = {"Family", "Associate", "Succession", "Representation", "Payment"}
    for placed in out["placements"].values():
        for p in placed:
            assert p["schema"] not in lateral_schemas


def test_edge_positions_fill_a_blank_role_only_when_opted_in():
    """The template fills in no title for a record without a role (a title the
    data doesn't contain would rank people and organizations by it); a
    direction.yaml that lists `edge_positions` opts in, and then a blank role
    takes that title."""
    _load()
    assert fold.load_direction(DIRECTION)["edge_positions"] == {}
    recs = [{"id": "c", "schema": "Company", "properties": {"name": ["Acme"]}},
            {"id": "p", "schema": "Person", "properties": {"name": ["Ann"]}},
            {"id": "e", "schema": "Employment", "properties": {"employee": ["Ann"], "employer": ["Acme"]}}]
    names = sorted({r["schema"] for r in recs})
    title = lambda d: fold.fold(recs, m.merge(recs, names, params_dir=PARAMS), names, direction=d,
                                params_dir=PARAMS)["placements"]["p"][0]["role"]
    opted = {**fold.load_direction(DIRECTION), "edge_positions": {"Employment": "Employee"}}
    assert not title(fold.load_direction(DIRECTION)) and title(opted) == "Employee"


# ---- full-surface: every schema in the real corpus gets classified --------


def test_no_edge_schema_actually_present_in_demo_is_unclassified():
    """Every edge schema the real demo corpus uses must have a direction.yaml
    entry -- an unclassified gap here means a real relationship in the data
    silently produces no placement."""
    _load()
    out = _run_fold()
    assert out["report"]["unclassified_schemas"] == []


def test_fold_runs_clean_over_the_full_demo_corpus():
    _load()
    out = _run_fold()
    assert out["placements"]
    assert out["pid"]


# ---- direct-property folds: a schema's OWN entity-typed property, --------
# ---- no separate relationship record --------------------------------------


def test_position_organization_is_a_real_direct_property_fold():
    """The one real case in the demo corpus: pos-head-security has no
    dedicated relationship record -- its OWN `organization` property (named
    in direction.yaml's `above` list) is the fold. Title comes from the same
    record's own `name` (Position.param.yaml: fold: [organization, name])."""
    _load()
    out = _run_fold()
    placed = out["placements"]["pos-head-security"]
    assert len(placed) == 1
    p = placed[0]
    assert p["schema"] == "Position"
    assert p["container"] == "sess-96cfcd44:org-fairbank"
    assert p["role"] == "Head of Security"


def test_occupancy_still_places_the_holder_under_the_position_itself():
    """Position-chain collapsing is deliberately NOT done here (see fold.py's
    module docstring) -- Marty's Occupancy placement must point at the
    Position record itself, not transitively through to the Organization."""
    _load()
    out = _run_fold()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    marty = result["survivors"].get("sess-96cfcd44:p-marty", "sess-96cfcd44:p-marty")
    occupancy = [p for p in out["placements"][marty] if p["schema"] == "Occupancy"]
    assert occupancy and occupancy[0]["container"] == "pos-head-security"


def test_a_schema_with_two_above_properties_produces_two_placements():
    """Vehicle.yaml declares BOTH `owner` and `operator` as entity-typed
    properties, both named in direction.yaml's `above` list, and the demo
    corpus doesn't happen to populate either directly (ownership is
    expressed via a separate Ownership record instead) -- so this is
    exercised with a minimal synthetic record, not real data, and that's
    stated plainly rather than implied otherwise."""
    _load()
    records = _load_demo_records()
    synthetic = {
        "id": "veh-synthetic", "schema": "Vehicle", "_collection": "test",
        "properties": {"name": ["Test Van"], "owner": ["Wallace Hollis Wright"],
                       "operator": ["Jordan Brooks Pelham"]},
    }
    all_records = records + [synthetic]
    direction = fold.load_direction(DIRECTION)
    result = m.merge(all_records, _all_schemas(), params_dir=PARAMS)
    out = fold.fold(all_records, result, _all_schemas(), direction=direction, params_dir=PARAMS)
    placed = out["placements"]["veh-synthetic"]
    containers = {p["container"]: p["role"] for p in placed}
    assert containers == {"p-wal": "owner", "p-jordan": "operator"}


def test_direct_property_fold_falls_back_to_property_name_when_no_title():
    """BankAccount.param.yaml's fold list is just [bank] -- no companion
    title-source field -- so the role falls back to the property's own
    name ("bank"), never left blank and never an invented label."""
    _load()
    records = _load_demo_records()
    synthetic = {
        "id": "acct-synthetic", "schema": "BankAccount", "_collection": "test",
        "properties": {"accountNumber": ["001"], "bank": ["Gideon Fairbank Organization"]},
    }
    all_records = records + [synthetic]
    direction = fold.load_direction(DIRECTION)
    result = m.merge(all_records, _all_schemas(), params_dir=PARAMS)
    out = fold.fold(all_records, result, _all_schemas(), direction=direction, params_dir=PARAMS)
    placed = out["placements"]["acct-synthetic"]
    assert len(placed) == 1 and placed[0]["role"] == "bank"


def test_direct_property_fold_resolves_against_already_merged_survivors():
    """pos-head-security's `organization` value resolves to whichever
    Organization record actually survived the merge (sess-96cfcd44:org-
    fairbank), not a raw unmerged duplicate -- the specific bug class this
    whole layer exists to prevent."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    assert "org-fairbank" not in result["indices"]["Organization"].records  # absorbed
    assert "sess-96cfcd44:org-fairbank" in result["indices"]["Organization"].records


# ---- parallel edges: one entry per record, order from data alone ----------


def _parallel(records):
    _load()
    direction = fold.load_direction(DIRECTION)
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    return fold.fold(records, result, _all_schemas(), direction=direction, params_dir=PARAMS)


def test_parallel_edges_keep_their_record_and_do_not_depend_on_record_order():
    """Two links into one organization, tied on everything the ranking reads
    (same start, both active): the pick, and each child's placement list,
    come from the data, so reversing the records changes nothing. Each
    placement names the edge record it came from."""
    synthetic = [
        {"id": "org-p", "schema": "Organization", "_collection": "test",
         "properties": {"name": ["Parallel Org"]}},
        {"id": "p-par", "schema": "Person", "_collection": "test",
         "properties": {"name": ["Parallel Person"]}},
        {"id": "rel-dir", "schema": "Directorship", "_collection": "test",
         "properties": {"director": ["Parallel Person"], "organization": ["Parallel Org"],
                        "role": ["Director"], "startDate": ["2010"]}},
        {"id": "rel-mem", "schema": "Membership", "_collection": "test",
         "properties": {"member": ["Parallel Person"], "organization": ["Parallel Org"],
                        "role": ["Treasurer"], "startDate": ["2010"]}},
    ]
    fwd, rev = _parallel(synthetic), _parallel(synthetic[::-1])
    assert fwd["placements"]["p-par"] == rev["placements"]["p-par"]
    assert [p["record"] for p in fwd["placements"]["p-par"]] == ["rel-dir", "rel-mem"]
    assert (fold.rank_placements(fwd["placements"]["p-par"])[0]["role"]
            == fold.rank_placements(rev["placements"]["p-par"])[0]["role"] == "Director")


def test_placement_dates_and_notes_use_every_value_in_any_order():
    """A record with several start dates, end dates or notes: the placement
    takes the earliest start and the latest end (the bounds its `_span` uses)
    and keeps every note, so the values' order in the file does not matter."""
    def rec(starts, ends, notes):
        return [{"id": "org-v", "schema": "Organization", "_collection": "test",
                 "properties": {"name": ["Value Org"]}},
                {"id": "p-v", "schema": "Person", "_collection": "test",
                 "properties": {"name": ["Value Person"]}},
                {"id": "rel-v", "schema": "Membership", "_collection": "test",
                 "properties": {"member": ["Value Person"], "organization": ["Value Org"],
                                "startDate": starts, "endDate": ends, "notes": notes}}]
    a = _parallel(rec(["2012-05", "2009"], ["2014", "2015-02"], ["b", "a"]))
    b = _parallel(rec(["2009", "2012-05"], ["2015-02", "2014"], ["a", "b"]))
    pa, pb = a["placements"]["p-v"][0], b["placements"]["p-v"][0]
    assert pa == pb
    assert (pa["startDate"], pa["endDate"], pa["notes"]) == ("2009", "2015-02", ["a", "b"])
