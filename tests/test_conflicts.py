"""A sameAs row names the distinct fields its two records disagree on, so a
manual confirm is made with the clash in view; kinds stay enforced."""


import test_fold as t  # noqa: E402
from hydra import schema  # noqa: E402
from hydra.identity import merge as m  # noqa: E402
from hydra.review import ids  # noqa: E402


def rec(id_, sch, **props):
    return {"id": id_, "schema": sch, "_collection": f"c-{id_}",
            "properties": {k: v if isinstance(v, list) else [v] for k, v in props.items()}}


def run(records, verdicts=None):
    t._load()
    return m.merge(records, sorted(schema.SCHEMA), params_dir=t.PARAMS, verdicts=verdicts)


def row(res, a, b):
    key = ids.merge_key(*sorted((a, b)))
    return next(r for r in res["identical"] if r["id"] == key)


JONS = [rec("a", "Person", name="Jon Smith", birthDate="1970"),
        rec("b", "Person", name="Jon Smith", birthDate="1985")]


def test_a_distinct_conflict_row_lists_the_clashing_fields():
    r = row(run(JONS), "a", "b")
    assert r["status"] == "proposed" and r["criteria"] == "distinct field conflict"
    assert r["conflicts"] == [{"prop": "birthDate", "a": ["1970"], "b": ["1985"]}]


def test_rows_without_a_clash_carry_no_conflicts_key():
    r = row(run([rec("a", "Person", name="Jon Smith"), rec("b", "Person", name="Jon Smith")]), "a", "b")
    assert "conflicts" not in r


def test_a_manual_confirm_merges_keeps_both_values_and_still_shows_the_clash():
    k = row(run(JONS), "a", "b")["id"]
    res = run(JONS, {k: "confirmed"})
    r = row(res, "a", "b")
    assert r["status"] == "confirmed" and r["conflicts"]
    keep = res["survivors"].get("a") or res["survivors"].get("b")
    final = next(i.records[keep] for i in res["indices"].values() if keep in i.records)
    assert sorted(final["properties"]["birthDate"]) == ["1970", "1985"]


def test_kinds_are_still_enforced_for_a_manual_link():
    recs = [rec("p", "Person", name="Alex Doe"), rec("o", "Organization", name="Alexander Doe Ltd"),
            {"id": "s", "schema": "Similar", "_collection": "c-s",
             "properties": {"candidate": ["Alex Doe"], "match": ["Alexander Doe Ltd"]}}]
    base = run(recs)
    k = next(r["id"] for r in base["identical"] if {r["a"], r["b"]} == {"p", "o"})
    res = run(recs, {k: "confirmed"})
    assert row(res, "p", "o")["status"] == "conflict" and not res["survivors"]
