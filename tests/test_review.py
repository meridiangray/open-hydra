"""review.py: ambiguous references become rows (never auto-resolved), a
pin verdict applies, a rejected (NOT sameAs) verdict persists, and a
rejected pair merged through other links surfaces as a contradiction."""

import yaml


import test_fold as t  # noqa: E402
from hydra.identity import merge as m  # noqa: E402
from hydra.review import ids, ledger as review  # noqa: E402
from hydra.shape import reads, rules  # noqa: E402
from hydra.structure import fold  # noqa: E402

GENERIC = t.TEMPLATE / ".hydra" / "rules" / "defaults" / "positions.yaml"


def _build(records, verdicts=None):
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    g = yaml.safe_load(GENERIC.read_text(encoding="utf-8")) or {}
    return reads.build_reads(records, rules.compile_rules(g, None, direction=fam),
                             verdicts=verdicts, direction=fam, params_dir=t.PARAMS)


def _walter_row(ir):
    rows = [r for r in ir["ledger"] if r["rel"] == "references" and r["value"] == "Walter White"]
    assert len(rows) == 1
    return rows[0]


def test_ambiguous_walter_white_is_a_row_not_a_guess():
    ir = _build(t._load_demo_records())
    row = _walter_row(ir)
    ids = {c["id"] for c in row["candidates"]}
    assert row["status"] == "proposed" and row["choice"] is None
    assert {"p-walt", "p-waltjr"} <= ids
    jr = next(n for n in ir["nodes"].values() if n["caption"] == "Walter White Jr.")
    assert jr["pid"] is None
    assert row["group"] == f"{row['schema']}.{row['prop']}"
    assert ir["report"]["reference_groups"][row["group"]] >= 1


def test_pin_verdict_resolves_that_one_reference_only():
    base = _build(t._load_demo_records())
    row = _walter_row(base)
    pinned = _build(t._load_demo_records(), {row["id"]: "p-walt"})
    prow = next(r for r in pinned["ledger"] if r["id"] == row["id"])
    assert prow["status"] == "pinned" and prow["choice"] == "p-walt"
    count = lambda ir: len(ir["report"]["fold"]["ambiguous_endpoints"])
    assert count(pinned) == count(base) - 1


def test_pin_to_a_vanished_record_is_ignored_not_followed():
    base = _build(t._load_demo_records())
    row = _walter_row(base)
    again = _build(t._load_demo_records(), {row["id"]: "no-such-record"})
    assert _walter_row(again)["status"] == "proposed"


def _same_name(n):
    return [{"id": f"x{i}", "schema": "Person", "properties": {"name": ["Jon Snow"]},
             "_collection": f"c{i}"} for i in range(n)]


def test_rejected_sameas_persists_and_blocks_that_link():
    recs = _same_name(2)
    key = ids.merge_key("x0", "x1")
    ir = _build(recs, {key: "rejected"})
    row = next(r for r in ir["ledger"] if r["id"] == key)
    assert row["status"] == "rejected"
    assert len([n for n in ir["nodes"].values() if n["caption"] == "Jon Snow"]) == 2


def test_rejected_pair_merged_through_others_is_a_contradiction():
    recs = _same_name(3)
    ir = _build(recs, {ids.merge_key("x0", "x2"): "rejected"})
    contra = ir["report"]["contradictions"]
    assert len(contra) == 1 and {contra[0]["a"], contra[0]["b"]} == {"x0", "x2"}
    assert any(r["rel"] == "contradiction" for r in ir["ledger"])


def test_no_contradiction_when_rejection_is_honored():
    ir = _build(_same_name(2), {ids.merge_key("x0", "x1"): "rejected"})
    assert ir["report"]["contradictions"] == []


# ---- group cascade + basis/confirmed-stale ---------------------------------


def _fork():
    return [
        {"id": "b", "schema": "Person", "properties": {"name": ["Walter White"]}, "_collection": "c0"},
        {"id": "w1", "schema": "Person", "properties": {"name": ["Walter Hartwell White"]}, "_collection": "c1"},
        {"id": "w2", "schema": "Person", "properties": {"name": ["Walter Gale White"]}, "_collection": "c2"},
    ]


def _row(ir, a, b):
    key = ids.merge_key(*sorted((a, b)))
    return next(r for r in ir["ledger"] if r["id"] == key)


def test_fork_rows_share_a_group():
    ir = _build(_fork())
    r1, r2 = _row(ir, "b", "w1"), _row(ir, "b", "w2")
    assert r1["status"] == r2["status"] == "proposed"
    assert r1["group"] and r1["group"] == r2["group"]


def test_confirming_one_fork_row_rejects_its_sibling_only():
    base = _build(_fork())
    k1 = _row(base, "b", "w1")["id"]
    ir = _build(_fork(), {k1: "confirmed"})
    assert _row(ir, "b", "w1")["status"] == "confirmed"
    sib = _row(ir, "b", "w2")
    assert sib["status"] == "rejected" and sib["cascaded_from"] == k1
    nodes = ir["nodes"]
    assert len(nodes) == 2                       # b+w1 merged, w2 stays separate
    merged = next(n for n in nodes.values() if n["id"] != "w2")
    assert set(merged["props"]["name"]) == {"Walter White", "Walter Hartwell White"}
    assert nodes["w2"]["caption"] == "Walter Gale White"


def test_an_explicit_second_decision_is_not_overridden_by_cascade():
    base = _build(_fork())
    k1, k2 = _row(base, "b", "w1")["id"], _row(base, "b", "w2")["id"]
    ir = _build(_fork(), {k1: "confirmed", k2: "confirmed"})
    assert _row(ir, "b", "w2")["status"] == "confirmed"
    assert "cascaded_from" not in _row(ir, "b", "w2")


def test_confirm_with_matching_basis_applies():
    base = _build(_fork())
    row = _row(base, "b", "w1")
    ir = _build(_fork(), {row["id"]: {"status": "confirmed", "basis": row["basis"]}})
    assert _row(ir, "b", "w1")["status"] == "confirmed"


def test_confirm_goes_stale_when_evidence_changes_and_is_not_applied():
    base = _build(_fork())
    row = _row(base, "b", "w1")
    verdict = {"status": "confirmed", "basis": row["basis"]}
    changed = _fork()
    changed[0]["properties"]["weakAlias"] = ["Heisenberg"]       # new match evidence
    ir = _build(changed, {row["id"]: verdict})
    r = _row(ir, "b", "w1")
    assert r["status"] == "confirmed-stale" and r["was"] == "confirmed"
    assert sum(n["caption"] == "Walter White" for n in ir["nodes"].values()) == 1  # not merged
    assert any(d["ledger"] == r["id"] for d in ir["report"]["duplicates"])


def test_rejection_stays_applied_when_stale_but_is_flagged():
    base = _build(_fork())
    row = _row(base, "b", "w1")
    changed = _fork()
    changed[0]["properties"]["weakAlias"] = ["Heisenberg"]
    ir = _build(changed, {row["id"]: {"status": "rejected", "basis": row["basis"]}})
    r = _row(ir, "b", "w1")
    assert r["status"] == "rejected" and r["stale"] is True


def test_bare_string_verdicts_still_work_with_no_staleness_check():
    base = _build(_fork())
    row = _row(base, "b", "w1")
    changed = _fork()
    changed[0]["properties"]["weakAlias"] = ["Heisenberg"]
    ir = _build(changed, {row["id"]: "confirmed"})
    assert _row(ir, "b", "w1")["status"] == "confirmed"


def test_provenance_pointers_are_not_review_rows():
    ir = _build(t._load_demo_records())
    groups = ir["report"]["reference_groups"]
    assert not any(g.startswith(("Page.", "Documentation.document")) for g in groups)
    assert "Membership.member" in groups                          # the real question remains
    rows = [r for r in ir["ledger"] if r["rel"] == "references"]
    assert rows and all(r["range"] != "Document" and r["range"] != "Pages" for r in rows)


# ---- report-only evidence: traced back to the values, never blocking -------


def _co(id_, **props):
    return {"id": id_, "schema": "Company", "_collection": "c",
            "properties": {k: [v] for k, v in props.items()}}


def test_contradiction_traces_the_links_and_values_that_overrode_it():
    """A ~ B on a name, B ~ C on B's alias, A ~ C rejected for clashing dates:
    the merge stands (report only) and the row shows the clash and both links,
    each with the values it matched on."""
    recs = [_co("a", name="Acme Ltd", email="info@acme.example", incorporationDate="1990"),
            _co("b", name="Acme Ltd", alias="Acme Trading"),
            _co("c", name="Acme Trading", email="info@acme.example", incorporationDate="2015")]
    ir = _build(recs, {ids.merge_key("a", "c"): "rejected"})
    (row,) = ir["report"]["contradictions"]
    assert row["conflicts"] == [{"prop": "incorporationDate", "a": ["1990"], "b": ["2015"]}]
    assert [(p["a"], p["b"]) for p in row["path"]] == [("a", "b"), ("b", "c")]
    assert row["path"][1]["shared"] == [{"a_prop": "alias", "a": "Acme Trading",
                                         "b_prop": "name", "b": "Acme Trading", "how": "exact"}]
    assert len({n["id"] for n in ir["nodes"].values()}) == 1      # still merged


def test_a_link_whose_ends_merged_is_a_self_edge_row_with_the_merge_behind_it():
    """`Alpha Holding` owns `Alpha Holding AG`, and the two merged on a shared
    registration number: the ownership is reported with the link that joined
    its ends; the merge stands and no node is placed under itself."""
    recs = [_co("c1", name="Alpha Holding AG", registrationNumber="HRB1"),
            _co("c3", name="Alpha Holding", registrationNumber="HRB1"),
            {"id": "o5", "schema": "Ownership", "_collection": "c",
             "properties": {"owner": ["Alpha Holding"], "asset": ["Alpha Holding AG"]}}]
    ir = _build(recs)
    (row,) = [r for r in ir["ledger"] if r["rel"] == "selfEdge"]
    assert row["record"] == "o5" and row["status"] == "conflict"
    assert [e["records"] for e in row["ends"]] == [["c3"], ["c1"]]
    (link,) = row["path"]
    assert {(s["a_prop"], s["a"]) for s in link["shared"]} >= {("registrationNumber", "HRB1")}
    assert all(n.get("pid") != rid for rid, n in ir["nodes"].items())


def test_a_link_naming_one_record_twice_is_a_self_edge_with_no_merge():
    recs = [_co("c1", name="Solo Ltd"),
            {"id": "o1", "schema": "Ownership", "_collection": "c",
             "properties": {"owner": ["Solo Ltd"], "asset": ["Solo Ltd"]}}]
    (row,) = _build(recs)["report"]["self_edges"]
    assert row["path"] == [] and "same record" in row["criteria"]


def test_the_demo_has_no_self_edges():
    assert _build(t._load_demo_records())["report"]["self_edges"] == []
