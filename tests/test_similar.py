"""`Similar` record handling (MODEL.md §4), against the real demo corpus.
`dce.json`'s `sim-hawthorne` is the first and only real Similar record in
the corpus — {candidate: "Hawthorne", match: "Wallace Hollis Wright"},
analyst note: "lands proposed in the ledger for a verdict".
"""
import json
from pathlib import Path


from hydra import schema  # noqa: E402
from hydra.identity import merge as m  # noqa: E402

from _paths import HYDRA as ROOT  # noqa: E402
from _paths import DEMO as DEMO_DIR  # noqa: E402
TEMPLATE = ROOT / "src" / "hydra" / "template"
PARAMS = TEMPLATE / ".hydra" / "schema" / "params"
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


def _sim_rows(result):
    return [e for e in result["identical"] if e.get("similar")]


# ---- the bootstrap problem: Similar's OWN candidate value is ambiguous ----


def test_similar_candidate_value_is_itself_ambiguous_by_strict_resolution():
    """The reason Similar can't use the strict resolver: "Hawthorne" is
    itself ambiguous between p-hawthorne-dce (name="Hawthorne") and
    p-wal (weakAlias="Hawthorne") -- exactly the case Similar exists to
    resolve. A strict resolver would refuse to ever fire on it."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    resolved_id, how, candidates = m.resolve_reference(
        "Hawthorne", "Thing", _all_schemas(), result["indices"])
    assert resolved_id is None and how == "ambiguous"
    assert set(candidates) >= {"p-hawthorne-dce", "p-wal"}


# ---- the main, intended row ------------------------------------------------


def test_sim_hawthorne_produces_the_intended_proposed_row():
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    rows = _sim_rows(result)
    main = [e for e in rows if {e["a"], e["b"]} == {"p-hawthorne-dce", "p-wal"}]
    assert main
    assert main[0]["status"] == "proposed"  # never auto, matching the old engine


def test_similar_never_auto_even_with_no_conflicting_data():
    """Confirms the hardcoded invariant from the old engine: a Similar row
    is `proposed` unconditionally, never promoted to `auto` by anything."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    assert all(e["status"] in ("proposed", "confirmed", "rejected")
               for e in _sim_rows(result))
    assert not any(e["status"] == "auto" for e in _sim_rows(result))


# ---- the honest trade-off: permissive search also surfaces weak noise -----


def test_similar_also_surfaces_a_weaker_implausible_pairing():
    """index.py:search() is deliberately permissive (every tier, not just
    the one a strict resolver accepts) -- so "Hawthorne" also weakly
    subset-matches org-hawthorne's weakAlias "Hawthorne Organization",
    producing a second, much weaker proposed row alongside the real one.
    This is accepted, not a bug: both are `proposed`, a human filters the
    implausible one in two seconds, and nothing is ever silently dropped."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    rows = _sim_rows(result)
    weak = [e for e in rows if {e["a"], e["b"]} == {"org-hawthorne", "p-wal"}]
    assert weak and weak[0]["status"] == "proposed"


# ---- confirming it: same-class absorption works, cross-class is a no-op --


def test_confirming_the_same_class_pair_merges_properties_onto_p_wal():
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    main = next(e for e in _sim_rows(result) if {e["a"], e["b"]} == {"p-hawthorne-dce", "p-wal"})
    result2 = m.merge(records, _all_schemas(), params_dir=PARAMS,
                      verdicts={main["id"]: "confirmed"})
    assert result2["survivors"]["p-hawthorne-dce"] == "p-wal"
    wal = result2["indices"]["Person"].records["p-wal"]
    assert "the Hawthorne" in wal["properties"]["weakAlias"]
    assert "p-hawthorne-dce" not in result2["indices"]["Person"].records


def test_confirming_a_cross_class_pair_never_corrupts_the_real_survivor():
    """The bug found and fixed while building this: a tied raw property-KEY
    count across two different schemas (Organization vs. Person) is not a
    meaningful comparison -- confirming it must never repoint `p-wal`'s own
    survivor id onto an Organization record. Confirmed as a structural
    no-op: the ledger row exists, nothing about p-wal changes."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    weak = next(e for e in _sim_rows(result) if {e["a"], e["b"]} == {"org-hawthorne", "p-wal"})
    result2 = m.merge(records, _all_schemas(), params_dir=PARAMS,
                      verdicts={weak["id"]: "confirmed"})
    assert "p-wal" not in result2["survivors"]
    assert "org-hawthorne" not in result2["survivors"]
    assert "p-wal" in result2["indices"]["Person"].records
    assert "org-hawthorne" in result2["indices"]["Organization"].records


def test_rejecting_a_similar_row_changes_nothing():
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    main = next(e for e in _sim_rows(result) if {e["a"], e["b"]} == {"p-hawthorne-dce", "p-wal"})
    result2 = m.merge(records, _all_schemas(), params_dir=PARAMS,
                      verdicts={main["id"]: "rejected"})
    assert "p-hawthorne-dce" not in result2["survivors"]
    row = next(e for e in _sim_rows(result2) if {e["a"], e["b"]} == {"p-hawthorne-dce", "p-wal"})
    assert row["status"] == "rejected"


def test_merge_with_similar_wired_in_is_still_deterministic():
    _load()
    records = _load_demo_records()
    r1 = m.merge(records, _all_schemas(), params_dir=PARAMS)
    r2 = m.merge(records, _all_schemas(), params_dir=PARAMS)
    assert [e["id"] for e in r1["identical"]] == [e["id"] for e in r2["identical"]]
    assert r1["survivors"] == r2["survivors"]


# ---- Similar rows are ordinary sameAs rows: grouped, cascaded, kind-checked --


def _merge_with(records, verdicts=None):
    _load()
    return m.merge(records, _all_schemas(), params_dir=PARAMS, verdicts=verdicts)


def _sim(id_, cand, match):
    return {"id": id_, "schema": "Similar", "_collection": "c",
            "properties": {"candidate": [cand], "match": [match]}}


def _p(id_, schema_, name, **extra):
    return {"id": id_, "schema": schema_, "_collection": f"c-{id_}",
            "properties": {"name": [name], **{k: [v] for k, v in extra.items()}}}


def test_confirming_the_intended_hawthorne_row_rejects_its_sibling():
    records = _load_demo_records()
    base = _merge_with(records)
    main = next(e for e in _sim_rows(base) if {e["a"], e["b"]} == {"p-hawthorne-dce", "p-wal"})
    other = next(e for e in _sim_rows(base) if e is not main)
    assert main["group"] and main["group"] == other["group"]
    res = _merge_with(records, {main["id"]: "confirmed"})
    rows = {e["id"]: e for e in _sim_rows(res)}
    assert rows[main["id"]]["status"] == "confirmed"
    assert rows[other["id"]]["status"] == "rejected"
    assert rows[other["id"]]["cascaded_from"] == main["id"]


def test_an_explicit_second_confirm_is_left_alone():
    records = _load_demo_records()
    base = _merge_with(records)
    ids = [e["id"] for e in _sim_rows(base)]
    res = _merge_with(records, {i: "confirmed" for i in ids})
    assert {e["status"] for e in _sim_rows(res)} <= {"confirmed", "conflict"}


def test_confirming_a_cross_kind_similar_is_flagged_not_silent():
    recs = [_p("per", "Person", "Alex Doe"), _p("org", "Organization", "Alexander Doe Ltd"),
            _sim("s1", "Alex Doe", "Alexander Doe Ltd")]
    base = _merge_with(recs)
    row = next(e for e in _sim_rows(base) if {e["a"], e["b"]} == {"per", "org"})
    res = _merge_with(recs, {row["id"]: "confirmed"})
    got = next(e for e in _sim_rows(res) if e["id"] == row["id"])
    assert got["status"] == "conflict" and "different kinds of thing" in got["criteria"]
    assert res["survivors"].get("per", "per") == "per" and res["survivors"].get("org", "org") == "org"


def test_confirming_a_similar_between_compatible_schemas_merges_into_the_specific_one():
    recs = [_p("gen", "LegalEntity", "Acme Holdings"), _p("co", "Company", "Acme Group"),
            _sim("s2", "Acme Holdings", "Acme Group")]
    base = _merge_with(recs)
    row = next(e for e in _sim_rows(base) if {e["a"], e["b"]} == {"gen", "co"})
    res = _merge_with(recs, {row["id"]: "confirmed"})
    assert res["survivors"].get("gen") == "co"
    assert "co" in res["indices"]["Company"].records and "gen" not in res["indices"]["LegalEntity"].records


def test_two_confirmed_similar_rows_sharing_a_record_join_all_three():
    """`Anna` ~ `Hanna` and `Anna` ~ `A. Kowalska`, both confirmed: one entity,
    whichever record keeps the id. The second absorb must use the survivor the
    first one left, or a record that was absorbed is re-absorbed and the third
    record stays apart."""
    import itertools
    from hydra.review import ids as ids_mod
    names = ["Anna Kowalski", "Hanna Kovalsky", "A. Kowalska"]
    extra = [{}, {"nationality": "pl"}, {"nationality": "pl", "birthDate": "1970"}]
    for richness in itertools.permutations(extra):
        recs = [_p(f"p{i}", "Person", n, **x) for i, (n, x) in enumerate(zip(names, richness))]
        recs += [_sim("s1", names[0], names[1]), _sim("s2", names[0], names[2])]
        rows = _sim_rows(_merge_with(recs))
        res = _merge_with(recs, {e["id"]: "confirmed" for e in rows})
        roots = {ids_mod.survivor(res["survivors"], f"p{i}") for i in range(3)}
        assert len(roots) == 1, richness
