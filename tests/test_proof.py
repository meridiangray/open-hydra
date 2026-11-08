"""Only proof merges on its own (same_name: review, hydra's default), and two posts
of one body are never one post because they share it."""
import json

import pytest

from hydra.cli import export as hexport
from hydra.cli import init as hinit
from hydra.cli.answer import set_verdict
from hydra import layout
from hydra.review import ids

P = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: v if isinstance(v, list) else [v] for k, v in p.items()}}


def archive(tmp_path, collections, manifest_extra=""):
    root = hinit.create(tmp_path / "a", name="a", prefix="a")
    for name, recs in collections.items():
        (root / "collections" / f"{name}.json").write_text(json.dumps(recs), encoding="utf-8")
    if manifest_extra:
        m = root / "hydra.yaml"
        m.write_text(m.read_text(encoding="utf-8") + manifest_extra + "\n", encoding="utf-8")
    return root


def merged(root) -> dict:
    cap = hexport.compile_(root)
    r = cap["resolved"]
    return {rid: ids.survivor(r.survivors, rid) for rid in (rec["id"] for rec in r.records)}, cap["ledger"]


TWO_ANNS = {"case": [P("p1", "Person", name="Ann Lee", birthDate="1970")],
            "reg": [P("r1", "Person", name="Ann Lee", nationality="gb")]}


@pytest.mark.proof
def test_an_exact_name_alone_is_proposed_not_merged(tmp_path):
    root = archive(tmp_path, TWO_ANNS)
    surv, ledger = merged(root)
    assert surv["a:p1"] != surv["a:r1"]
    row = next(r for r in ledger if r.get("rel") == "sameAs")
    assert row["status"] == "proposed" and "no proof" in row["criteria"]
    set_verdict(root / layout.VERDICTS, row["id"], "confirmed")       # a person decides
    surv, _ = merged(root)
    assert surv["a:p1"] == surv["a:r1"]


@pytest.mark.proof
def test_an_identifier_is_proof(tmp_path):
    root = archive(tmp_path, {"case": [P("p1", "Person", name="Ann Lee", idNumber="X-1")],
                              "reg": [P("r1", "Person", name="A. Lee", idNumber="X1")]})
    surv, _ = merged(root)
    assert surv["a:p1"] == surv["a:r1"]


@pytest.mark.proof
def test_an_archive_or_a_type_can_take_names_as_identity(tmp_path):
    root = archive(tmp_path, TWO_ANNS, "same_name: merge")
    surv, _ = merged(root)
    assert surv["a:p1"] == surv["a:r1"]
    (root / "hydra.yaml").write_text((root / "hydra.yaml").read_text(encoding="utf-8").replace("same_name: merge", ""),
                                     encoding="utf-8")
    params = root / layout.PARAMS_DIR / "Person.param.yaml"
    params.write_text(params.read_text(encoding="utf-8") + "\nsame_name: merge\n", encoding="utf-8")
    surv, _ = merged(root)
    assert surv["a:p1"] == surv["a:r1"]


@pytest.mark.proof
def test_a_name_still_resolves_a_link(tmp_path):
    """A link by name is a reference, not a merge: it still finds its record."""
    root = archive(tmp_path, {"case": [P("p1", "Person", name="Ann Lee"), P("o1", "Company", name="Lee Ltd"),
                                       P("d1", "Directorship", director="Ann Lee", organization="Lee Ltd")]})
    cap = hexport.compile_(root)
    refs = cap["resolved"].tscan.get("refs") or {}
    assert any(v == ["a:p1"] for (rid, prop, _), v in refs.items() if prop == "director")


def test_two_posts_of_one_body_are_two_posts(tmp_path):
    """Even when names merge, a shared organization is no evidence two posts are one."""
    body = P("m", "PublicBody", name="Ministry of Interior")
    root = archive(tmp_path, {"posts": [body,
                                        P("x1", "Position", name="Minister of Interior", organization="Ministry of Interior"),
                                        P("x2", "Position", name="Deputy Minister of Interior", organization="Ministry of Interior"),
                                        P("x3", "Position", name="Adviser to the Minister of Interior",
                                          organization="Ministry of Interior")]})
    surv, _ = merged(root)
    assert len({surv["a:x1"], surv["a:x2"], surv["a:x3"]}) == 3
