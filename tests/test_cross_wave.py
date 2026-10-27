"""The secondary pass for is-a compatible classes that sit in different waves:
a generic record and its specific counterpart meet after the main entity
process, are decided by the same rules, and merge into the specific one."""


import pytest  # noqa: E402

import test_fold as t  # noqa: E402
from hydra import schema  # noqa: E402
from hydra.identity import merge as m, order  # noqa: E402
from hydra.review import ids  # noqa: E402


def rec(id_, sch, **props):
    return {"id": id_, "schema": sch, "_collection": f"c-{id_}",
            "properties": {k: v if isinstance(v, list) else [v] for k, v in props.items()}}


def run(records, verdicts=None):
    t._load()
    return m.merge(records, sorted(schema.SCHEMA), params_dir=t.PARAMS, verdicts=verdicts)


def row(res, a, b):
    key = ids.merge_key(*sorted((a, b)))
    return next((r for r in res["identical"] if r["id"] == key), None)


def final_schema(res, rid):
    keep = res["survivors"].get(rid, rid)
    return next(i.records[keep]["schema"] for i in res["indices"].values() if keep in i.records)


PAIRS = [  # (generic schema, specific schema, props shared by both)
    ("Event", "Trip", {"name": "Desert cook run"}),
    ("Identification", "Passport", {"number": "X1234567"}),
    ("Asset", "BankAccount", {"name": "Acme operating account"}),
    ("Contract", "License", {"name": "Spectrum licence 7"}),
    ("Asset", "Contract", {"name": "Supply agreement 9"}),
]


def _wave(c):
    t._load()
    waves = order.resolve_order(sorted(schema.SCHEMA), t.PARAMS)
    return next(i for i, w in enumerate(waves) if c in w)


@pytest.mark.parametrize("generic,specific,props", PAIRS)
def test_the_pair_really_is_split_across_waves(generic, specific, props):
    assert _wave(generic) != _wave(specific)


@pytest.mark.parametrize("generic,specific,props", PAIRS)
def test_generic_and_specific_merge_into_the_specific_class(generic, specific, props):
    res = run([rec("g", generic, **props), rec("s", specific, **props)])
    r = row(res, "g", "s")
    assert r is not None and r["cross_wave"] and r["status"] == "auto"
    assert "across waves" in r["criteria"]
    assert final_schema(res, "g") == final_schema(res, "s") == specific
    assert res["survivors"].get("g") == "s" or res["survivors"].get("s") == "g"


def test_different_names_do_not_merge():
    res = run([rec("g", "Event", name="Wayfarer collision"), rec("s", "Trip", name="Desert cook run")])
    assert row(res, "g", "s") is None
    assert not res["survivors"]


def test_a_rejected_verdict_keeps_them_apart():
    recs = [rec("g", "Event", name="Desert cook run"), rec("s", "Trip", name="Desert cook run")]
    key = row(run(recs), "g", "s")["id"]
    res = run(recs, {key: "rejected"})
    assert row(res, "g", "s")["status"] == "rejected" and not res["survivors"]


def test_a_generic_matching_two_incompatible_specifics_is_a_fork_for_a_human():
    recs = [rec("g", "Asset", name="Acme"), rec("b", "BankAccount", name="Acme"),
            rec("k", "Contract", name="Acme")]
    res = run(recs)
    rb, rk = row(res, "g", "b"), row(res, "g", "k")
    assert rb["status"] == rk["status"] == "proposed"
    assert rb["group"] and rb["group"] == rk["group"]
    assert not res["survivors"]
    # confirming one rejects the other
    res2 = run(recs, {rb["id"]: "confirmed"})
    assert row(res2, "g", "b")["status"] == "confirmed" and row(res2, "g", "k")["status"] == "rejected"
    assert final_schema(res2, "g") == "BankAccount"


def test_same_wave_pairs_are_not_decided_twice():
    res = run([rec("a", "Event", name="Same"), rec("b", "Event", name="Same")])
    assert sum(1 for r in res["identical"] if {r["a"], r["b"]} == {"a", "b"}) == 1
    assert not any(r.get("cross_wave") for r in res["identical"])


def test_the_merged_properties_survive_on_the_specific_record():
    res = run([rec("g", "Event", name="Desert cook run", description="a cook"),
               rec("s", "Trip", name="Desert cook run", startDate="2008")])
    keep = res["survivors"].get("g") or res["survivors"].get("s") or "s"
    final = next(i.records[keep] for i in res["indices"].values() if keep in i.records)
    assert final["properties"]["description"] == ["a cook"] and final["properties"]["startDate"] == ["2008"]
