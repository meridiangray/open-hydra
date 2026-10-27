"""Layer 4 is-a compatibility: a generic LegalEntity/Organization record can
specialize into a subtype and merge with it; incompatible kinds never merge;
a generic matching several kinds is a fork for a human."""


import test_fold as t  # noqa: E402
from hydra import schema  # noqa: E402
from hydra.identity import merge as m  # noqa: E402
from hydra.review import ids  # noqa: E402


def rec(id_, sch, *names):
    return {"id": id_, "schema": sch, "_collection": f"c-{id_}",
            "properties": {"name": list(names)}}


def run(records, verdicts=None):
    t._load()
    return m.merge(records, sorted(schema.SCHEMA), params_dir=t.PARAMS, verdicts=verdicts)


def row(res, a, b):
    key = ids.merge_key(*sorted((a, b)))
    return next((r for r in res["identical"] if r["id"] == key), None)


def survivor_schema(res, rid):
    keep = res["survivors"].get(rid, rid)
    return next(i.records[keep]["schema"] for i in res["indices"].values() if keep in i.records)


def test_generic_legal_entity_specializes_into_the_company_it_matches():
    res = run([rec("g", "LegalEntity", "Acme Holdings"), rec("c", "Company", "Acme Holdings")])
    r = row(res, "g", "c")
    assert r["status"] == "auto" and "generic LegalEntity -> Company" in r["criteria"]
    assert res["survivors"]["g"] == "c" or res["survivors"]["c"] == "g"
    assert survivor_schema(res, "g") == "Company" == survivor_schema(res, "c")
    assert "Company" in res["indices"] and any(
        i.schema_name == "Company" and len(i.records) == 1 for i in res["indices"].values())
    assert not res["indices"]["LegalEntity"].records            # absorbed, not left behind


def test_specific_schema_wins_even_when_the_generic_record_has_more_properties():
    g = rec("g", "LegalEntity", "Acme Holdings")
    g["properties"]["country"] = ["us"]
    g["properties"]["notes"] = ["a", "b"]
    res = run([g, rec("c", "Company", "Acme Holdings")])
    assert survivor_schema(res, "g") == "Company"
    merged = next(r for i in res["indices"].values() for r in i.records.values() if r["schema"] == "Company")
    assert merged["properties"]["country"] == ["us"]            # generic's data kept


def test_provenance_records_which_schema_supplied_each_value():
    res = run([rec("g", "LegalEntity", "Acme Holdings"), rec("c", "Company", "Acme Holdings")])
    assert {c["schema"] for c in res["claims"]} == {"LegalEntity", "Company"}


def test_incompatible_kinds_never_get_a_row():
    res = run([rec("p", "Person", "Jon Snow"), rec("c", "Company", "Jon Snow")])
    assert row(res, "p", "c") is None and not res["survivors"]


def test_generic_matching_two_kinds_is_a_fork_not_an_auto_merge():
    res = run([rec("g", "LegalEntity", "Acme"), rec("c", "Company", "Acme"),
               rec("p", "Person", "Acme")])
    rc, rp = row(res, "g", "c"), row(res, "g", "p")
    assert rc["status"] == rp["status"] == "proposed"
    assert "generic matches several kinds" in rc["criteria"]
    assert rc["group"] and rc["group"] == rp["group"]
    assert row(res, "c", "p") is None and not res["survivors"]


def test_confirming_one_fork_row_specializes_and_rejects_the_sibling():
    base = run([rec("g", "LegalEntity", "Acme"), rec("c", "Company", "Acme"), rec("p", "Person", "Acme")])
    k = row(base, "g", "c")["id"]
    res = run([rec("g", "LegalEntity", "Acme"), rec("c", "Company", "Acme"), rec("p", "Person", "Acme")],
              {k: "confirmed"})
    assert row(res, "g", "p")["status"] == "rejected"
    assert survivor_schema(res, "g") == "Company"
    assert survivor_schema(res, "p") == "Person"


def test_company_and_publicbody_are_incompatible_so_a_generic_organization_forks():
    res = run([rec("o", "Organization", "Zeta"), rec("c", "Company", "Zeta"),
               rec("b", "PublicBody", "Zeta")])
    assert row(res, "o", "c")["status"] == row(res, "o", "b")["status"] == "proposed"
    assert row(res, "c", "b") is None


def test_organization_generic_merges_with_a_single_company():
    res = run([rec("o", "Organization", "Zeta"), rec("c", "Company", "Zeta")])
    assert row(res, "o", "c")["status"] == "auto" and survivor_schema(res, "o") == "Company"


def test_transitive_join_of_incompatible_kinds_is_blocked_deterministically():
    recs = [rec("l1", "LegalEntity", "Alpha", "Beta"), rec("c", "Company", "Alpha"),
            rec("l2", "LegalEntity", "Beta", "Gamma"), rec("p", "Person", "Gamma")]
    res = run(recs)
    rows = [row(res, "l1", "c"), row(res, "l1", "l2"), row(res, "l2", "p")]
    demoted = [r for r in rows if r["status"] == "proposed"]
    assert len(demoted) == 1 and "would join incompatible kinds" in demoted[0]["criteria"]
    assert survivor_schema(res, "c") == "Company" and survivor_schema(res, "p") == "Person"
    assert run(recs)["identical"] == res["identical"]           # same corpus, same result


def test_same_schema_merging_is_unchanged():
    res = run([rec("a", "Person", "Jon Snow"), rec("b", "Person", "Jon Snow")])
    assert row(res, "a", "b")["status"] == "auto" and survivor_schema(res, "a") == "Person"
