"""Step 3a: same exact name + scope decides auto vs proposed; only FIRM
scope can auto-merge. Cyclic / phantom / ambiguous scope is evidence the
engine will not act on alone. Synthetic corpora, one collection per file."""


import test_fold as t  # noqa: E402
from hydra import schema  # noqa: E402
from hydra.identity import merge as m  # noqa: E402
from hydra.structure import fold  # noqa: E402


def rec(coll, id_, sch, **props):
    return {"id": id_, "schema": sch, "_collection": coll,
            "properties": {k: v if isinstance(v, list) else [v] for k, v in props.items()}}


def person_in(coll, pid, org=None, **extra):
    rs = [rec(coll, pid, "Person", name="Jon Snow", **extra)]
    if org:
        rs.append(rec(coll, f"{pid}-m", "Membership", member="Jon Snow", organization=org))
    return rs


def run(records, verdicts=None, direction=True):
    t._load()
    fam = fold.load_direction(t.DIRECTION) if direction else None
    return m.merge(records, sorted(schema.SCHEMA), params_dir=t.PARAMS, verdicts=verdicts, direction=fam)


def jon_row(res):
    rows = [r for r in res["identical"] if r["acap"] == "Jon Snow" and r["bcap"] == "Jon Snow"]
    assert len(rows) == 1, rows
    return rows[0]


def orgs(*names):
    return [rec("c0", f"o-{n.replace(' ', '')}", "Organization", name=n) for n in names]


def test_shared_firm_scope_across_collections_auto_merges():
    recs = orgs("Acme Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Acme Org")
    r = jon_row(run(recs))
    assert r["status"] == "auto" and r["criteria"] == "same name, shared scope"
    assert r["scope"]["kind"] == "firm"


def test_different_firm_scopes_propose_never_auto():
    recs = orgs("Acme Org", "Beta Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Beta Org")
    r = jon_row(run(recs))
    assert r["status"] == "proposed" and r["criteria"] == "same name, different scope"


def test_one_side_without_an_org_proposes():
    recs = orgs("Acme Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2")
    r = jon_row(run(recs))
    assert r["status"] == "proposed" and r["criteria"] == "same name, one has no org"


def test_neither_side_has_an_org_auto_merges_like_the_old_engine():
    r = jon_row(run(person_in("c1", "p1") + person_in("c2", "p2")))
    assert r["status"] == "auto" and r["criteria"] == "same name" and r["scope"]["kind"] == "none"


def test_phantom_shared_scope_is_evidence_but_only_a_suggestion():
    recs = person_in("c1", "p1", "Mystery Org") + person_in("c2", "p2", "Mystery Org")
    r = jon_row(run(recs))
    assert r["status"] == "proposed" and "unsettled (phantom)" in r["criteria"]
    assert r["scope"]["kind"] == "unsettled"


def test_ambiguous_shared_scope_is_also_unsettled():
    recs = orgs("Acme Holdings", "Acme Ventures") + person_in("c1", "p1", "Acme") + person_in("c2", "p2", "Acme")
    r = jon_row(run(recs))
    assert r["status"] == "proposed" and "unsettled (ambiguous)" in r["criteria"]


def test_membership_cycle_among_orgs_makes_shared_component_unsettled():
    cyc = [rec("c0", "m-a", "Membership", member="Org One", organization="Org Two"),
           rec("c0", "m-b", "Membership", member="Org Two", organization="Org One")]
    recs = orgs("Org One", "Org Two") + cyc + person_in("c1", "p1", "Org One") + person_in("c2", "p2", "Org Two")
    r = jon_row(run(recs))
    assert r["status"] == "proposed" and "unsettled (cyclic)" in r["criteria"]
    assert {k for k, _ in map(tuple, r["scope"]["a"])} == {k for k, _ in map(tuple, r["scope"]["b"])}


def test_identifier_match_is_hard_evidence_scope_cannot_demote_it():
    recs = (orgs("Acme Org", "Beta Org")
            + person_in("c1", "p1", "Acme Org", passportNumber="X123")
            + person_in("c2", "p2", "Beta Org", passportNumber="X123"))
    r = jon_row(run(recs))
    assert r["status"] == "auto" and "scope" not in r


def test_without_families_behavior_is_unchanged():
    recs = orgs("Acme Org", "Beta Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Beta Org")
    r = jon_row(run(recs, direction=False))
    assert r["status"] == "auto" and "scope" not in r


def test_containers_with_the_same_name_merge_without_scope():
    res = run([rec("c1", "o1", "Organization", name="Acme Org"), rec("c2", "o2", "Organization", name="Acme Org")])
    r = next(r for r in res["identical"] if r["acap"] == "Acme Org")
    assert r["status"] == "auto" and "scope" not in r


def test_verdicts_override_the_scope_decision_both_ways():
    recs = orgs("Acme Org", "Beta Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Beta Org")
    key = jon_row(run(recs))["id"]
    assert jon_row(run(recs, {key: "confirmed"}))["status"] == "confirmed"
    shared = orgs("Acme Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Acme Org")
    assert jon_row(run(shared, {jon_row(run(shared))["id"]: "rejected"}))["status"] == "rejected"


def test_confirm_goes_stale_when_the_scope_it_rested_on_changes():
    recs = orgs("Acme Org", "Beta Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Beta Org")
    row = jon_row(run(recs))
    verdict = {"status": "confirmed", "basis": row["basis"]}
    moved = orgs("Acme Org", "Beta Org", "Gamma Org") + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Gamma Org")
    r = jon_row(run(moved, {row["id"]: verdict}))
    assert r["status"] == "confirmed-stale"
    same = jon_row(run(recs, {row["id"]: verdict}))
    assert same["status"] == "confirmed"


def test_scope_does_not_read_an_orgs_own_parent():
    """Organization.parent may point at a Person; scope must never follow it."""
    org = rec("c0", "o1", "Organization", name="Acme Org", parent="Jon Snow")
    recs = [org] + person_in("c1", "p1", "Acme Org") + person_in("c2", "p2", "Acme Org")
    assert jon_row(run(recs))["status"] == "auto"
