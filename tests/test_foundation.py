"""Foundation smoke tests: the copied layout/model/store load cleanly from
the package's own template/, and Layer 1 (types.py) behaves correctly against
real demo records. Run with:

    python3 -m pytest
"""
from pathlib import Path


from hydra import ingest as records, schema  # noqa: E402
from hydra.identity import types as t  # noqa: E402
from _paths import DEMO as DEMO_DIR, TEMPLATE as TEMPLATE_DIR  # noqa: E402

TEMPLATE = TEMPLATE_DIR
DEMO = DEMO_DIR


def _load_template():
    schema.load(root=str(TEMPLATE))


def test_schema_loads_from_hydra_template():
    _load_template()
    assert "Person" in schema.SCHEMA
    assert "Membership" in schema.SCHEMA


def test_params_files_do_not_leak_into_person_properties():
    """.hydra/schema/params/Person.param.yaml must not be ingested as a type patch
    (the one deliberate fix in this copy of model/schema.py's _role())."""
    _load_template()
    props = schema.resolve("Person")["props"]
    assert "match" not in props
    assert "distinct" not in props
    assert "fold" not in props
    assert "birthDate" in props  # real Person property, sanity check


def test_membership_edge_and_range_metadata_present():
    """Layer 3/5 depend on this metadata existing — confirm it's there."""
    _load_template()
    e = schema.SCHEMA["Membership"].get("edge")
    assert e and e["source"] == "member" and e["target"] == "organization"
    props = schema.resolve("Membership")["props"]
    assert props["organization"]["type"] == "entity"
    assert props["organization"]["range"] == "Organization"


def test_demo_corpus_parses_with_records_py():
    """The corrected demo corpus (natural values, no id-references) still
    parses cleanly through the untouched records.py."""
    text = (DEMO / "hawthorne.json").read_text(encoding="utf-8")
    recs = records.parse_records(text)
    wal = next(r for r in recs if r["id"] == "p-wal")
    assert wal["properties"]["name"] == ["Wallace Hollis Wright"]
    membership = next(r for r in recs if r["id"] == "rel-hb1")
    # this is the corrected value — natural name, not the old "p-wal" id
    assert membership["properties"]["member"] == ["Wallace Hollis Wright"]


# ---- Layer 1 (types.py), exercised against the real Wallace Wright case -----


def test_name_exact_match():
    c = t.compare("name", "Wallace Hollis Wright", "Wallace Hollis Wright")
    assert c.signal is t.Signal.MATCH and c.how == "exact"


def test_name_word_subset_match():
    """"Wallace Wright" (fairbank-condensed.json) is a word-subset of the primary
    entity's full name — MATCH, not a fuzzy-ratio coincidence."""
    c = t.compare("name", "Wallace Wright", "Wallace Hollis Wright")
    assert c.signal is t.Signal.MATCH and c.how == "subset"


def test_name_mismatch_is_neutral_not_conflict():
    """A name difference alone never blocks a merge — only a `distinct`
    field's CONFLICT does. "Wallace Wright" vs "Jordan Pelham" share no words."""
    c = t.compare("name", "Wallace Wright", "Jordan Pelham")
    assert c.signal is t.Signal.NEUTRAL


def test_identifier_exact_and_conflict():
    assert t.compare("identifier", "P-123 456", "p123456").signal is t.Signal.MATCH
    assert t.compare("identifier", "P123456", "P999999").signal is t.Signal.CONFLICT


def test_date_partial_overlap_and_disjoint():
    assert t.compare("date", "2008", "2008-06-15").how == "overlap"
    assert t.compare("date", "2008", "2010").signal is t.Signal.CONFLICT


def test_email_mismatch_is_neutral_never_conflict():
    """email/phone/url are corroborating only — never identity-bearing
    enough to block a merge on mismatch (two people sharing a household
    address/phone must never read as a CONFLICT)."""
    c = t.compare("email", "wal@example.com", "sasha@example.com")
    assert c.signal is t.Signal.NEUTRAL


def test_missing_value_is_always_neutral():
    assert t.compare("identifier", "", "P123456").signal is t.Signal.NEUTRAL
    assert t.compare("date", "not-a-date", "2008").signal is t.Signal.NEUTRAL


def test_entity_type_is_deferred_not_compared():
    import pytest
    with pytest.raises(NotImplementedError):
        t.compare("entity", "org-fairbank", "org-fairbank")


def test_unknown_future_type_degrades_to_neutral():
    assert t.compare("some-new-type-from-2027", "a", "b").signal is t.Signal.NEUTRAL
