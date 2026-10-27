"""Layer 4a (index.py) tests: ClassIndex's generalized type dispatch, and
search() as the human-facing pick-list mechanism for exactly the cases
merge.py's strict resolve_reference() refuses to guess on.
"""
import json
from pathlib import Path


from hydra import schema  # noqa: E402
from hydra.identity import classify, index as index_mod, merge as m  # noqa: E402

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


# ---- generalized dispatch: email/phone/url/address were silently invisible


def test_email_phone_url_are_indexed_not_silently_skipped():
    """Before types.EXACT_TYPES/TOKEN_TYPES dispatch, ClassIndex only
    handled identifier/iban/name -- email/phone/url (match=True by
    classify.py's own default) were silently invisible."""
    _load()
    pc = classify.classify("Person", PARAMS)
    records = [
        {"id": "p1", "schema": "Person", "properties": {"name": ["A One"], "email": ["a@example.com"]}},
        {"id": "p2", "schema": "Person", "properties": {"name": ["B Two"], "email": ["a@example.com"]}},
    ]
    idx = index_mod.build_index(records, "Person", pc)
    assert idx.candidate_ids(records[0], pc) == {"p2"}


def test_address_full_is_indexed_via_token_types():
    """Address.param.yaml promotes `full` (ftm_type=address) to match=True.
    Before the dispatch generalization, address-typed fields had no
    comparator at all and were invisible to ClassIndex."""
    _load()
    pc = classify.classify("Address", PARAMS)
    assert pc["full"].match  # confirm the override actually promotes it
    records = [
        {"id": "a1", "schema": "Address", "properties": {"full": ["Albuquerque, New Mexico, United States"]}},
    ]
    idx = index_mod.build_index(records, "Address", pc)
    assert idx.match_value("Albuquerque", "address") == {"a1"}


# ---- search(): ranked, permissive browse against the real demo corpus -----


def test_search_ranks_the_real_walter_white_candidates_above_the_weak_one():
    """The exact case that motivated search(): resolve_reference() correctly
    refuses to pick among p-walt/p-waltjr/org-heisenberg for bare "Walter
    White" -- but a human looking at a pick-list should see the two real
    Person candidates ranked above the weak Organization one, since their
    matching name values are closer in length to the query."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, sorted(schema.SCHEMA), params_dir=PARAMS)
    hits = index_mod.search("Walter White", result["indices"], limit=10)
    ids_in_order = [h.record_id for h in hits]
    assert "p-walt" in ids_in_order and "p-waltjr" in ids_in_order
    assert "org-heisenberg" in ids_in_order
    assert ids_in_order.index("p-walt") < ids_in_order.index("org-heisenberg")
    assert ids_in_order.index("p-waltjr") < ids_in_order.index("org-heisenberg")


def test_search_is_explainable_not_a_black_box():
    """Every hit carries raw token counts a human/UI can show directly --
    no single opaque score."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, sorted(schema.SCHEMA), params_dir=PARAMS)
    hits = index_mod.search("Walter White", result["indices"])
    walt = next(h for h in hits if h.record_id == "p-walt")
    assert walt.how == "name-subset"
    assert walt.query_tokens == 2
    assert walt.shared_tokens == 2
    assert walt.candidate_tokens == 3  # "Walter Hartwell White"


def test_search_surfaces_the_heisenberg_identity_question():
    """A different real case: "Heisenberg" is ambiguous between
    p-heisenberg-dea and p-walt (a genuine identity question, not a
    reference-pin one -- see MODEL.md §4, this needs a Similar record, not
    a pick-list decision -- but search() should still surface both so a
    human reviewing a Similar record has an easy way to find both ids)."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, sorted(schema.SCHEMA), params_dir=PARAMS)
    hits = index_mod.search("Heisenberg", result["indices"])
    ids = {h.record_id for h in hits}
    assert "p-walt" in ids
    assert "p-heisenberg-dea" in ids


def test_search_exact_match_outranks_subset():
    _load()
    records = _load_demo_records()
    result = m.merge(records, sorted(schema.SCHEMA), params_dir=PARAMS)
    hits = index_mod.search("Walter Hartwell White", result["indices"])
    assert hits[0].record_id == "p-walt"
    assert hits[0].how == "name-exact"


def test_search_returns_nothing_for_zero_token_overlap():
    """Documented limit: search() cannot find a candidate sharing zero
    words with the query -- confirms it fails closed (empty list), not by
    guessing via some other mechanism."""
    _load()
    records = _load_demo_records()
    result = m.merge(records, sorted(schema.SCHEMA), params_dir=PARAMS)
    hits = index_mod.search("Zzyzx Qwerty Nonexistent", result["indices"])
    assert hits == []
