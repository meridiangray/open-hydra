"""Full-schema-surface coverage gates — run against EVERY loaded schema and
EVERY param.yaml file, never a hand-picked subset.

These exist because of a specific, real failure mode: logic validated by
hand against 2-3 example schemas (Person, Organization, Membership) ships
looking correct, while the other ~35 schemas in schema/ftm/followthemoney/
silently misbehave because nobody ran anything against them. Each test here
re-derives its expectation from the live schema on every run — it is a
check against reality, not a list of remembered facts that can go stale.

Run with: python3 -m pytest -v
"""
import glob
from pathlib import Path

import yaml


from hydra import schema  # noqa: E402

from _paths import HYDRA as ROOT  # noqa: E402
from _paths import DEMO as DEMO_DIR  # noqa: E402
TEMPLATE = ROOT / "src" / "hydra" / "template"
PARAM_FILES = sorted(glob.glob(str(TEMPLATE / ".hydra" / "schema" / "params" / "*.param.yaml")))


def _load():
    schema.load(root=str(TEMPLATE))


def test_every_param_file_field_is_a_real_property():
    """Catches drift: a <Type>.param.yaml listing match/distinct/fold fields
    that no longer exist on the live schema (renamed/removed upstream)."""
    _load()
    drift = []
    for pf in PARAM_FILES:
        doc = yaml.safe_load(open(pf)) or {}
        sname = doc.get("schema") or Path(pf).stem.split(".param")[0]
        assert sname in schema.SCHEMA, f"{pf}: schema {sname!r} does not exist"
        props = schema.resolve(sname)["props"]
        for cat in ("match", "distinct", "fold"):
            for p in doc.get(cat) or []:
                if p not in props:
                    drift.append(f"{sname}.{cat}: {p!r} is not a real property")
    assert not drift, "param.yaml drift:\n" + "\n".join(drift)


def test_every_entity_typed_property_has_a_resolvable_range():
    """A `range` that resolves to zero concrete schemas is a dead end for
    order.py's class graph — this would mean a relationship nobody could
    ever actually fold onto anything."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    dead_ends = []
    for sname in all_schemas:
        for p, pd in schema.resolve(sname)["props"].items():
            if pd.get("type") != "entity" or not pd.get("range"):
                continue
            concretes = [s for s in all_schemas if schema.is_a(s, pd["range"])
                         and not schema.SCHEMA[s].get("abstract", False)]
            if not concretes:
                dead_ends.append(f"{sname}.{p} ranges over {pd['range']!r}, "
                                  "0 concrete schemas satisfy it")
    assert not dead_ends, "\n".join(dead_ends)


def test_wide_ranges_are_not_all_flagged_abstract():
    """Documents the specific bug this file exists to prevent: `abstract`
    is NOT a reliable signal for "does this range need is-a expansion".
    If this ever starts failing because every wide range got its flag
    fixed upstream, that's good news — relax the assertion, don't delete
    the test; the coverage check above still has to run against the real
    is-a closure regardless of what the flag says."""
    _load()
    all_schemas = sorted(schema.SCHEMA)
    wide, unflagged_wide = {}, []
    for sname in all_schemas:
        for p, pd in schema.resolve(sname)["props"].items():
            if pd.get("type") != "entity" or not pd.get("range"):
                continue
            rng = pd["range"]
            concretes = {s for s in all_schemas if schema.is_a(s, rng)
                         and not schema.SCHEMA[s].get("abstract", False)}
            if len(concretes) > 1:
                wide.setdefault(rng, concretes)
    for rng in wide:
        if not schema.SCHEMA[rng].get("abstract", False):
            unflagged_wide.append(rng)
    # as of this writing: LegalEntity, Document, Asset, Folder, Organization,
    # Vehicle, Contract are all wide (>1 concrete schema) and abstract=False.
    assert unflagged_wide, (
        "expected at least one wide, unflagged range to exist — if this "
        "assertion fails, re-verify order.py never branches on `abstract`"
    )
    assert "LegalEntity" in unflagged_wide, (
        "LegalEntity (51 properties, 5 concrete classes, abstract=False) "
        "is the canary for this whole test file"
    )


def test_every_schema_used_in_demo_corpus_has_param_coverage_or_is_flagged():
    """Every schema actually appearing in demo/collections/*.json either has
    a <Type>.param.yaml or is explicitly accounted for — no silent gap
    between "what we tested" and "what real data uses"."""
    import json
    demo_dir = DEMO_DIR
    used = set()
    for f in sorted(demo_dir.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(d, list):
            used |= {r.get("schema") for r in d}
    have_params = {Path(p).stem.split(".param")[0] for p in PARAM_FILES}
    missing = used - have_params
    assert not missing, f"schemas used in demo/ with no param file: {sorted(missing)}"
