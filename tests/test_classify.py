"""Layer 2 (classify.py) tests. Three groups:

1. The three evidenced pipeline-metadata exclusions, against the real
   schemas that carry each property (not assumed targets — checked first).
2. A regression guard: known strong identifiers must NEVER be excluded.
3. Full-surface sweeps — classify() must run cleanly across every loaded
   schema, with and without its param file, not just the 3 this layer is
   scoped to implement against first.
"""
import glob
from pathlib import Path

import pytest


from hydra import schema  # noqa: E402
from hydra.identity import classify as c  # noqa: E402

from _paths import HYDRA as ROOT  # noqa: E402
TEMPLATE = ROOT / "src" / "hydra" / "template"
PARAMS_DIR = TEMPLATE / ".hydra" / "schema" / "params"


def _load():
    schema.load(root=str(TEMPLATE))


# ---- default_category: pure type formula -----------------------------------


def test_default_category_formula():
    assert c.default_category("identifier") == (True, True, False)
    assert c.default_category("name") == (True, False, False)
    assert c.default_category("email") == (True, False, False)
    assert c.default_category("date") == (False, True, False)
    assert c.default_category("country") == (False, True, False)
    assert c.default_category("entity") == (False, False, True)
    assert c.default_category("string") == (False, False, False)


# ---- the three pipeline-metadata exclusions, against real schemas ----------


def test_matchable_false_excludes_person_provenance_fields():
    _load()
    pc = c.classify("Person")
    for prop in ("sourceUrl", "publisherUrl", "retrievedAt"):
        assert not pc[prop].match and not pc[prop].distinct, prop


def test_hidden_excludes_person_program_id():
    _load()
    pc = c.classify("Person")
    assert not pc["programId"].match and not pc["programId"].distinct


def test_hidden_excludes_document_mentioned_family():
    _load()
    pc = c.classify("Document")
    for prop in ("namesMentioned", "peopleMentioned", "emailMentioned"):
        assert not pc[prop].match, prop


def test_at_suffix_excludes_distinct_even_without_matchable_flag():
    _load()
    pc = c.classify("Person")
    # createdAt/modifiedAt: pipeline timestamps, no `matchable:false` set
    # upstream on every declaring schema -> caught by the "*At" backstop
    for prop in ("createdAt", "modifiedAt"):
        assert not pc[prop].distinct, prop


def test_bare_date_and_date_suffix_fields_are_not_excluded():
    """The "*At" backstop must not over-fire on legitimate domain dates."""
    _load()
    pc = c.classify("Document")
    assert pc["date"].distinct
    person = c.classify("Person")
    assert person["birthDate"].distinct


# ---- regression guard: never exclude a genuine strong identifier ----------


def test_strong_identifiers_are_never_excluded():
    _load()
    for sname, props in (
        ("Person", ("passportNumber", "socialSecurityNumber", "idNumber", "wikidataId")),
        ("Organization", ("registrationNumber", "taxNumber", "leiCode", "wikidataId")),
    ):
        pc = c.classify(sname)
        for prop in props:
            assert pc[prop].match and pc[prop].distinct, f"{sname}.{prop}"


def test_entity_names_are_never_excluded():
    _load()
    for sname in ("Person", "Organization"):
        pc = c.classify(sname)
        for prop in ("name", "alias", "weakAlias", "previousName"):
            assert pc[prop].match, f"{sname}.{prop}"


def test_weak_alias_matchable_false_is_overridden_for_name_type():
    """Upstream FTM marks `weakAlias` matchable=false (confirmed: the only
    name-typed property anywhere with that flag). This system deliberately
    keeps it matchable by default — see _is_pipeline_metadata's docstring —
    because compare_name's word-subset + distinct-conflict check is exactly
    the safeguard upstream's blanket caution is protecting against."""
    _load()
    pdef = schema.resolve("Person")["props"]["weakAlias"]
    assert pdef["matchable"] is False  # the upstream fact this test guards
    assert c.classify("Person")["weakAlias"].match is True  # our override of it


def test_matchable_false_name_properties_are_exactly_weak_alias():
    """Regression guard for the exemption above: if upstream ever marks a
    SECOND name-typed property matchable=false, this fails loudly instead
    of silently re-including something that should stay excluded."""
    _load()
    hits = set()
    for sname in sorted(schema.SCHEMA):
        for prop, pdef in schema.resolve(sname)["props"].items():
            if pdef.get("type") == "name" and pdef.get("matchable") is False:
                hits.add(prop)
    assert hits == {"weakAlias"}


# ---- entity-typed -> fold, with range carried through ----------------------


def test_entity_typed_properties_are_fold_with_range():
    _load()
    pc = c.classify("Membership")
    assert pc["member"].fold and pc["member"].range == "LegalEntity"
    assert pc["organization"].fold and pc["organization"].range == "Organization"
    assert not pc["member"].match and not pc["member"].distinct


# ---- param.yaml as a diff: demotion and promotion, both directions --------


def test_param_override_promotes_plain_string_field():
    """Membership.role is plain `string`-typed (default: no category at
    all), but Membership.param.yaml explicitly promotes it to match+fold."""
    _load()
    pc = c.classify("Membership", params_dir=PARAMS_DIR)
    assert pc["role"].match and pc["role"].fold
    default_only = c.classify("Membership")
    assert not default_only["role"].match and not default_only["role"].fold


def test_an_unknown_param_property_is_skipped_and_reported(tmp_path):
    _load()
    (tmp_path / "Person.param.yaml").write_text(
        "schema: Person\nmatch: [name, totallyNotARealProperty]\n", encoding="utf-8")
    (tmp_path / "Nothing.param.yaml").write_text("match: [name]\n", encoding="utf-8")
    pc = c.classify("Person", params_dir=tmp_path)
    assert pc["name"].match and not pc["email"].match and "totallyNotARealProperty" not in pc
    issues = c.param_issues(tmp_path, schema.SCHEMA)
    assert any("totallyNotARealProperty" in i for i in issues)
    assert any("Nothing.param.yaml" in i for i in issues)


def test_missing_param_file_is_not_an_error():
    _load()
    pc = c.classify("Person", params_dir=PARAMS_DIR)  # Person.param.yaml exists
    pc2 = c.classify("Sanction", params_dir=PARAMS_DIR)  # also exists, sanity
    assert pc and pc2


# ---- full-surface sweeps: every loaded schema, not a hand-picked few ------


def test_classify_runs_clean_on_every_schema_with_no_param_file():
    """Layer 2's actual acceptance test (MODEL.md): correct from defaults
    alone, for ANY schema `schema.resolve()` can load — not just the 3
    this layer is scoped to implement against first."""
    _load()
    for sname in sorted(schema.SCHEMA):
        pc = c.classify(sname)  # must not raise
        for prop, pdef in schema.resolve(sname)["props"].items():
            if pdef.get("type") == "entity":
                assert pc[prop].fold, f"{sname}.{prop} is entity-typed but not fold"
                assert not pc[prop].match and not pc[prop].distinct, (
                    f"{sname}.{prop} entity-typed must never be match/distinct")


def test_classify_runs_clean_on_every_schema_with_a_param_file():
    """Every real <Type>.param.yaml in the template applies without error
    against the live schema — not just Person/Organization/Membership."""
    _load()
    for pf in sorted(glob.glob(str(PARAMS_DIR / "*.param.yaml"))):
        sname = Path(pf).stem.split(".param")[0]
        c.classify(sname, params_dir=PARAMS_DIR)  # must not raise


def test_no_entity_typed_property_is_ever_excluded_as_pipeline_metadata():
    """The three exclusion rules are about match/distinct noise, never
    about fold -- an entity-typed property (a real relationship endpoint)
    must never be suppressed, even if it happens to carry `hidden` or
    `matchable: false` for display purposes."""
    _load()
    for sname in sorted(schema.SCHEMA):
        pc = c.classify(sname)
        for prop, pdef in schema.resolve(sname)["props"].items():
            if pdef.get("type") == "entity":
                assert pc[prop].fold, f"{sname}.{prop}"

