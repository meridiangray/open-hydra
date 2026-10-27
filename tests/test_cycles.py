"""cycles.py tests — the cycle map is derived from the live schema, so these
pin the facts a human verified (the 20-row direct edge list, the DAG
bucket, the SCCs) and the invariants that must hold for any schema set."""
from pathlib import Path


from hydra import schema  # noqa: E402
from hydra.structure import cycles, fold  # noqa: E402

from _paths import HYDRA as ROOT  # noqa: E402
TEMPLATE = ROOT / "src" / "hydra" / "template"


def _map():
    schema.load(root=str(TEMPLATE))
    fam = fold.load_direction(TEMPLATE / ".hydra" / "schema" / "direction.yaml")
    return cycles.cycle_map(sorted(schema.SCHEMA), fam)


def test_direct_edge_rows_match_the_verified_list():
    m = _map()
    rows = {(c, l, p) for l, t in m["pairs"].items()
            if m["families"][l].kind == "edge" for c, p in t["direct"]}
    three = ["Company", "Organization", "PublicBody"]
    want = {("CourtCase", "CourtCaseParty", "CourtCase"), ("Company", "Ownership", "Company")}
    want |= {(a, e, b) for e in ("Directorship", "Membership") for a in three for b in three}
    assert rows == want and len(rows) == 20


def test_unconstrained_thing_edges_are_not_pathways():
    m = _map()
    assert "Placement" not in m["families"] and "UnknownLink" not in m["families"]


def test_cyclic_sccs():
    m = _map()
    assert sorted(m["sccs"]) == sorted([
        ["CourtCase"], ["RealEstate"],
        ["Email", "Folder", "Message", "Package", "Workbook"],
        ["Company", "Contract", "LegalEntity", "License", "Organization",
         "Person", "Position", "Project", "PublicBody"]])


def test_dag_bucket_needs_no_guard():
    m = _map()
    for l in ("Vehicle.owner", "BankAccount.bank", "Passport.holder", "Image.parent"):
        assert m["category"][l] == "dag"
    assert m["category"]["ContractAward"] == "bridge"
    assert m["category"]["Directorship"] == "self_family"
    assert m["category"]["RealEstate.parent"] == "self_loop"


def test_category_and_stub_candidates_are_independent():
    m = _map()
    assert m["category"]["Person.parent"] == "self_loop"
    sc = m["stub_candidates"]["Person.parent"]["parent"]
    assert not sc["determined"] and len(sc["classes"]) == 5
    assert m["stub_candidates"]["CourtCaseParty"]["parent"]["determined"]


def test_deterministic():
    assert _map()["pairs"] == _map()["pairs"] and _map()["sccs"] == _map()["sccs"]


def test_forms_follow_authored_direction_and_cycle_tier():
    m = _map()
    assert m["form"]["Vehicle.owner"] == "dag"
    assert m["form"]["Directorship"] == "combined"
    assert m["form"]["ProjectParticipant"] == "combined"      # authored dual
    assert {l for l, v in m["form"].items() if v == "ag"} >= {"Family", "Associate", "Payment", "Debt"}
    assert set(m["lateral"]) == {l for l, v in m["form"].items() if v == "ag"}


def test_person_director_loop_is_an_indirect_pair():
    """A Person director closes a loop only through `X.parent` (range LegalEntity,
    which includes Person): the pair is in the indirect tier, not direct."""
    m = _map()
    for p in ("Company", "Organization", "PublicBody"):
        assert ("Person", p) in m["pairs"]["Directorship"]["indirect"]
    assert m["pair_form"]["Directorship"][("Person", "Organization")] == "combined"


def test_lateral_families_never_enter_the_containment_graph():
    m = _map()
    assert not (set(m["lateral"]) & set(m["families"]))
    C = {"Company", "Organization", "PublicBody"}
    both = {l for l, f in m["lateral"].items() if f.children & C and f.parents & C}
    assert {"Debt", "Payment", "Representation", "Succession"} <= both


def test_project_hangs_under_a_legal_entity_or_another_project():
    m = _map()
    assert {"Project.organization", "Project.parent"} <= set(m["families"])
    props = schema.resolve("Project")["props"]
    assert props["organization"]["range"] == "LegalEntity" and props["organization"]["revname"] == "projects"
    assert props["parent"]["range"] == "Project" and props["parent"]["revname"] == "subprojects"
