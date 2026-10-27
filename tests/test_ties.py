"""ties.py + the IR's lateral/rels/linked, against the demo corpus (checked
against the old engine: the 40 real lateral ties match exactly) and small
synthetic cases."""

import yaml


import test_fold as t  # noqa: E402
from hydra.shape import reads, rules  # noqa: E402
from hydra.structure import fold  # noqa: E402

GENERIC = t.TEMPLATE / ".hydra" / "rules" / "defaults" / "positions.yaml"


def build(records, verdicts=None):
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    g = yaml.safe_load(GENERIC.read_text(encoding="utf-8")) or {}
    return reads.build_reads(records, rules.compile_rules(g, None, direction=fam),
                             verdicts=verdicts, direction=fam, params_dir=t.PARAMS)


def rec(id_, sch, coll="c", **props):
    return {"id": id_, "schema": sch, "_collection": coll,
            "properties": {k: v if isinstance(v, list) else [v] for k, v in props.items()}}


def real_lateral(ir):
    return [(n["caption"], l["to_caption"], l["schema"]) for n in ir["nodes"].values()
            for l in n["lateral"] if not l.get("dup")]


def test_demo_laterals_are_the_lateral_schemas_only():
    ir = build(t._load_demo_records())
    schemas = {s for _, _, s in real_lateral(ir)}
    assert {"Family", "Associate", "ProjectParticipant", "Representation", "Succession"} <= schemas
    assert not (schemas & {"Membership", "Directorship", "Employment", "Occupancy"})
    assert len(set(real_lateral(ir))) == 40       # identical to the old engine on this corpus


def test_rels_are_symmetric_per_record():
    ir = build(t._load_demo_records())
    nodes = ir["nodes"]
    seen = {(n["id"], r["at"], r["record"]) for n in nodes.values() for r in n["rels"]}
    both = {(a, b, rc) for a, b, rc in seen if b in nodes}      # Position ends are not nodes
    assert both and all((b, a, rc) in seen for a, b, rc in both)


def test_ambiguous_bare_name_membership_ties_only_the_resolvable_member_until_pinned():
    """rel-fr-cooks names TWO members: "Jesse Pinkman" resolves, bare "Walter
    White" is ambiguous (Walter / Walter Jr.) and must tie to neither."""
    def ends(ir):
        return {(n["id"], r["at"]) for n in ir["nodes"].values() for r in n["rels"]
                if r["record"] == "rel-fr-cooks"}
    ir = build(t._load_demo_records())
    touched = {x for pair in ends(ir) for x in pair}
    assert "p-walt" not in touched and "p-waltjr" not in touched and touched
    row = next(r for r in ir["ledger"] if r["rel"] == "references" and r["value"] == "Walter White")
    pinned = build(t._load_demo_records(), {row["id"]: "p-walt"})
    touched2 = {x for pair in ends(pinned) for x in pair}
    assert "p-walt" in touched2 and "p-waltjr" not in touched2


def test_linked_evidence_hangs_off_renderable_nodes_never_becomes_a_node():
    ir = build(t._load_demo_records())
    linked = [l for n in ir["nodes"].values() for l in n["linked"]]
    assert {"Event", "Trip", "Page"} <= {l["schema"] for l in linked}
    assert not any(l["id"] in ir["nodes"] for l in linked)
    assert ir["report"]["provenance"]["sourced"] > 0


def test_rels_flag_position_endpoints():
    ir = build(t._load_demo_records())
    assert any(r["pos"] for n in ir["nodes"].values() for r in n["rels"])


def test_undirected_lateral_edge_is_one_sided_tie_but_two_sided_rels():
    recs = [rec("a", "Person", name="Ann"), rec("b", "Person", name="Bob"),
            rec("f", "Family", person="Ann", relative="Bob", relationship="sibling")]
    ir = build(recs)
    assert [(l["to_caption"], l["schema"]) for l in ir["nodes"]["a"]["lateral"]] == [("Bob", "Family")]
    assert ir["nodes"]["b"]["lateral"] == []
    assert [r["at"] for r in ir["nodes"]["a"]["rels"]] == ["b"]
    assert [r["at"] for r in ir["nodes"]["b"]["rels"]] == ["a"]


def test_dual_edge_is_both_a_lateral_tie_and_a_placement():
    recs = [rec("p", "Person", name="Ann"), rec("pr", "Project", name="Alpha"),
            rec("pp", "ProjectParticipant", participant="Ann", project="Alpha", role="lead")]
    ir = build(recs)
    assert [l["schema"] for l in ir["nodes"]["p"]["lateral"]] == ["ProjectParticipant"]
    assert ir["nodes"]["p"]["pid"] == "pr"


def test_vertical_edge_is_not_lateral_and_above_prop_is_rels_only():
    recs = [rec("p", "Person", name="Ann"), rec("o", "Organization", name="Acme Org"),
            rec("m", "Membership", member="Ann", organization="Acme Org"),
            rec("v", "Vehicle", name="Van", owner="Acme Org")]
    ir = build(recs)
    assert ir["nodes"]["p"]["lateral"] == [] and ir["nodes"]["p"]["pid"] == "o"
    assert ir["nodes"]["v"]["lateral"] == []                      # `owner` is an above prop
    assert {r["via"] for r in ir["nodes"]["v"]["rels"]} == {"owner"}


def test_an_unresolvable_lateral_endpoint_is_reported_not_dropped_silently():
    recs = [rec("a", "Person", name="Ann"),
            rec("f", "Family", person="Ann", relative="Nobody At All", relationship="x")]
    ir = build(recs)
    assert any(u["value"] == "Nobody At All" for u in ir["report"]["ties"]["unresolved"])
    assert any(r["rel"] == "references" and r["value"] == "Nobody At All" for r in ir["ledger"])
    assert ir["nodes"]["a"]["lateral"] == []


def test_rels_are_deduplicated():
    ir = build(t._load_demo_records())
    for n in ir["nodes"].values():
        keys = [(r["at"], r["label"], r["via"], r["record"]) for r in n["rels"]]
        assert len(keys) == len(set(keys))
