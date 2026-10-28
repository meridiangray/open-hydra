"""Match strength: hard (identifier) and name matches can merge; soft types
(address, email, phone, url, date...) corroborate but never merge two records
that BOTH carry differing names. Found in the demo: two different buildings
in "Alderton, NM" (and two different events on one date) auto-merged."""


import test_fold as t  # noqa: E402
from hydra import schema  # noqa: E402
from hydra.identity import merge as m, types  # noqa: E402


def rec(id_, sch, **props):
    return {"id": id_, "schema": sch, "_collection": f"c-{id_}",
            "properties": {k: v if isinstance(v, list) else [v] for k, v in props.items()}}


def run(records):
    t._load()
    return m.merge(records, sorted(schema.SCHEMA), params_dir=t.PARAMS)


def only_row(res):
    assert len(res["identical"]) == 1, res["identical"]
    return res["identical"][0]


def test_strength_classification():
    assert [types.strength(x) for x in ("identifier", "iban", "checksum")] == ["hard"] * 3
    assert types.strength("name") == "name"
    assert {types.strength(x) for x in ("address", "email", "phone", "url", "date")} == {"soft"}


def test_two_differently_named_buildings_at_one_address_are_only_proposed():
    res = run([rec("a", "RealEstate", name="Casa Tranquila", address="Alderton, NM"),
               rec("b", "RealEstate", name="Lantern Bright", address="Alderton, NM")])
    r = only_row(res)
    assert r["status"] == "proposed" and r["criteria"] == "address match only, names differ"
    assert not res["survivors"]


def test_same_name_and_same_address_still_merges():
    res = run([rec("a", "RealEstate", name="Casa Tranquila", address="Alderton, NM"),
               rec("b", "RealEstate", name="Casa Tranquila", address="Alderton, NM")])
    assert only_row(res)["status"] == "auto" and res["survivors"]


def test_soft_match_with_one_side_unnamed_is_proposed():
    res = run([rec("a", "RealEstate", name="Casa Tranquila", address="Alderton, NM"),
               rec("b", "RealEstate", address="Alderton, NM")])
    assert only_row(res)["criteria"] == "address match only, one side unnamed"


def test_two_unnamed_records_with_the_same_address_text_still_merge():
    res = run([rec("a", "Address", full="12 Main St, Alderton"),
               rec("b", "Address", full="12 Main St, Alderton")])
    assert only_row(res)["status"] == "auto" and res["survivors"]


def test_exact_identifier_is_hard_evidence_even_when_names_differ():
    res = run([rec("a", "Company", name="Acme Ltd", registrationNumber="REG-1"),
               rec("b", "Company", name="Acme Limited", registrationNumber="REG-1")])
    assert only_row(res)["status"] == "auto"


def test_a_shared_email_alone_is_not_enough_for_two_named_companies():
    res = run([rec("a", "Company", name="Acme Ltd", email="info@acme.example"),
               rec("b", "Company", name="Beta Ltd", email="info@acme.example")])
    rows = res["identical"]
    assert not rows or all(r["status"] == "proposed" for r in rows)
    assert not res["survivors"]


def test_two_events_on_the_same_date_with_different_names_are_not_merged():
    res = run([rec("a", "Event", name="Exhibit", date="2010-01-01"),
               rec("b", "Event", name="Session", date="2010-01-01")])
    assert not res["survivors"]


def test_a_name_matches_the_other_records_alias():
    r = only_row(run([rec("a", "Person", name="Алексей Воронов", alias="Aleksei Voronov"),
                      rec("b", "Person", name="Aleksei Voronov")]))
    assert r["status"] == "auto" and "exact" in r["criteria"]


def test_a_weak_alias_equal_to_a_name_is_only_proposed():
    r = only_row(run([rec("a", "Person", name="Wallace Hollis Wright", weakAlias="Hawthorne"),
                      rec("b", "Person", name="Hawthorne")]))
    assert r["status"] == "proposed" and r["criteria"].startswith("weak-exact")


def test_a_weak_alias_that_is_one_word_of_a_name_is_no_pair():
    res = run([rec("a", "Person", name="Wallace Hollis Wright", weakAlias="Wal"),
               rec("b", "Person", name="Wal Jenkins")])
    assert res["identical"] == []
