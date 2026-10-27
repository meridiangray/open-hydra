"""Layer 4 (index.py + merge.py) tests, against the real corrected demo
corpus — not synthetic records. This is the actual proof that types.py,
classify.py, order.py and index.py compose correctly, and the named
acceptance bar from the original outline: "Walter White" must never
silently resolve to "Walter White Jr."
"""
import glob
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
        if not isinstance(data, list):
            continue
        for r in data:
            r = dict(r)
            r["_collection"] = f.stem
            records.append(r)
    return records


def _all_schemas():
    return sorted(schema.SCHEMA)


# ---- the named acceptance bar: never Walter White Jr. ----------------------


def test_walter_white_bare_name_is_ambiguous_never_silently_wrong():
    """fring-condensed.json's Membership.member = "Walter White" (no local
    Person record) word-subset-matches "Walter Hartwell White" (p-walt) and
    "Walter White Jr." (p-waltjr) -- and, found when this test was written,
    ALSO org-heisenberg's weakAlias "Walter White's operation" (its tokens
    are a superset of the query's too, structurally the same subset
    relationship, just a weaker candidate -- see test_search_ranks_the_real_
    walter_white_candidates_above_the_weak_one for how a human-facing search
    distinguishes them). The invariant that actually matters: it must be
    reported ambiguous, never silently resolved to any single candidate --
    especially never silently to p-waltjr alone."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    hits = [a for a in result["report"]["ambiguous_references"]
            if a["value"] == "Walter White" and a["prop"] == "member"]
    assert hits, "expected an ambiguous reference for bare 'Walter White'"
    candidates = set(hits[0]["candidates"])
    assert {"p-walt", "p-waltjr"} <= candidates


def test_walter_hartwell_white_full_name_resolves_cleanly_to_p_walt():
    """fring.json's rel-fr7.member and operations.json's pp-4/pp-8/pp-11
    all use the full exact name post-fix -- these must resolve cleanly,
    unlike the bare "Walter White" case above."""
    _load()
    records = _load_demo_records()
    by_id = {r["id"]: r for r in records}
    schema_names = _all_schemas()
    passes_done_through_person = ["Person"]  # Person is pass 0, resolves first
    indices = {}
    # exercise resolve_reference directly against a freshly-built Person index
    from hydra.identity import classify, index as index_mod
    person_records = [r for r in records if r["schema"] == "Person"]
    pc = classify.classify("Person", PARAMS)
    indices["Person"] = index_mod.build_index(person_records, "Person", pc)
    resolved_id, how, candidates = m.resolve_reference(
        "Walter Hartwell White", "LegalEntity", schema_names, indices)
    assert resolved_id == "p-walt"
    assert how == "name-exact"


# ---- real duplicate-record merging: Gustavo Fring across two collections --


def test_gustavo_fring_duplicate_person_records_auto_merge():
    """p-fring (fring-condensed.json) and sess-96cfcd44:p-fring (fring.json)
    are two separate Person records, same exact name, no distinct conflict
    -- must auto-merge, matching the old engine's own "same name, neither
    has known scope -> auto" behavior for this exact case."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    a, b = "p-fring", "sess-96cfcd44:p-fring"
    rows = [e for e in result["identical"] if {e["a"], e["b"]} == {a, b}]
    assert rows, "no sameAs row found for the two Gustavo Fring records"
    assert rows[0]["status"] == "auto"
    survivors = result["survivors"]
    assert (a in survivors) != (b in survivors)  # exactly one was absorbed


def test_distinct_conflict_demotes_to_proposed_never_dropped():
    """Two different real people sharing a name with a conflicting distinct
    field must still appear as a reviewable proposed row, never silently
    dropped -- construct a minimal synthetic pair since the demo corpus
    doesn't happen to contain this exact case."""
    _load()
    records = [
        {"id": "a1", "schema": "Person", "properties": {"name": ["John Smith"], "birthDate": ["1950-01-01"]}},
        {"id": "a2", "schema": "Person", "properties": {"name": ["John Smith"], "birthDate": ["1990-01-01"]}},
    ]
    result = m.merge(records, ["Person"], params_dir=PARAMS)
    rows = [e for e in result["identical"] if {e["a"], e["b"]} == {"a1", "a2"}]
    assert rows and rows[0]["status"] == "proposed"
    assert "conflict" in rows[0]["criteria"]
    assert not result["survivors"]  # neither side was merged away


# ---- full-surface: the whole demo corpus, all 72 schemas, no crash --------


def test_merge_runs_clean_over_the_full_demo_corpus_and_all_schemas():
    _load()
    records = _load_demo_records()
    result = m.merge(records, _all_schemas(), params_dir=PARAMS)
    assert result["identical"]
    assert result["claims"]
    # every survivor target must be a record id that actually exists
    ids = {r["id"] for r in records}
    for dropped, kept in result["survivors"].items():
        assert dropped in ids and kept in ids


def test_merge_is_deterministic():
    _load()
    records = _load_demo_records()
    r1 = m.merge(records, _all_schemas(), params_dir=PARAMS)
    r2 = m.merge(records, _all_schemas(), params_dir=PARAMS)
    assert r1["survivors"] == r2["survivors"]
    assert [e["id"] for e in r1["identical"]] == [e["id"] for e in r2["identical"]]
