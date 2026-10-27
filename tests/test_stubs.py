"""stubs.py and `hydra-ctl stubs`: a name some links hold that no record has,
listed, previewed in the tree, graduated by a decision, and always the loser
of a merge with a real record."""
import json

import pytest

from hydra import cli, layout, stubs
from hydra.review import verdicts as vd

GRAY = [{"id": "org", "schema": "Organization", "properties": {"name": ["Gray Matter Technologies"]}},
        {"id": "elliott", "schema": "Person", "properties": {"name": ["Elliott Schwartz"]}},
        {"id": "m1", "schema": "Membership", "properties": {"member": ["Elliott Schwartz"],
                                                            "organization": ["Gray Matter Technologies"],
                                                            "role": ["leader"]}},
        {"id": "m2", "schema": "Membership", "properties": {"member": ["Gretchen Schwartz"],
                                                            "organization": ["Gray Matter Technologies"],
                                                            "role": ["member"]}},
        {"id": "f1", "schema": "Family", "properties": {"person": ["Elliott Schwartz"],
                                                        "relative": ["gretchen schwartz"],
                                                        "relationship": ["spouse"]}}]


@pytest.fixture
def arch(tmp_path, capsys):
    a = tmp_path / "gm"
    cli.main(["init", str(a)])
    (a / layout.COLLECTIONS_DIR / "c.json").write_text(json.dumps(GRAY), encoding="utf-8")
    cli.main(["build", str(a)])
    capsys.readouterr()
    return a


def _out(capsys, *argv) -> str:
    capsys.readouterr()
    assert cli.main(list(argv)) == 0
    return capsys.readouterr().out


def test_a_name_no_record_has_is_found_with_what_it_fits(arch):
    (e,) = stubs.found(arch)
    assert e["slug"] == "gretchen-schwartz" and e["links"] == 2                 # either spelling, one name
    assert set(e["fields"]) == {"Membership.member", "Family.relative"}
    assert e["fits"] == "Person"                                               # Person is a LegalEntity


def test_the_tree_previews_stubs_without_saving_anything(arch, capsys):
    before = {p.name: p.read_bytes() for p in (arch / layout.PARSED_DIR).iterdir() if p.is_file()}
    plain = _out(capsys, "tree", str(arch))
    assert "Gretchen" not in plain
    preview = _out(capsys, "tree", str(arch), "--stubs")
    assert "Gretchen Schwartz (Person) — Member   stub" in preview
    after = {p.name: p.read_bytes() for p in (arch / layout.PARSED_DIR).iterdir() if p.is_file()}
    assert after == before and not stubs.decided(vd.load(arch)[0])


def test_graduating_is_a_decision_the_build_turns_into_one_entity(arch, capsys):
    out = _out(capsys, "stubs", "graduate", str(arch), "Gretchen Schwartz")
    assert "stub:gretchen-schwartz" in out and "Rebuilt " in out
    assert vd.load(arch)[0]["stub-gretchen-schwartz"] == "Person"
    assert stubs.found(arch) == []                                              # both links point at it now
    tree = _out(capsys, "tree", str(arch))
    assert "Gretchen Schwartz (Person) — Member   stub" in tree
    summary = _out(capsys, "todo", str(arch), "--format", "json")
    assert json.loads(summary)["references"] == []
    listed = _out(capsys, "stubs", str(arch))
    assert "Gretchen Schwartz" in listed and listed.rstrip().endswith("Person")
    assert "stub" not in _out(capsys, "check", str(arch)).split("errors")[0]      # no lint issue for the key
    _out(capsys, "stubs", "drop", str(arch), "gretchen schwartz")
    assert "Gretchen" not in _out(capsys, "tree", str(arch)) and len(stubs.found(arch)) == 1


def test_a_real_record_with_the_name_keeps_its_id(arch, capsys):
    _out(capsys, "stubs", "graduate", str(arch), "Gretchen Schwartz")
    (arch / layout.COLLECTIONS_DIR / "later.json").write_text(json.dumps(
        [{"id": "gretchen", "schema": "Person", "properties": {"name": ["Gretchen Schwartz"]}}]), encoding="utf-8")
    cli.main(["build", str(arch)])
    nodes = json.loads((arch / layout.PARSED_DIR / "declared.json").read_text(encoding="utf-8"))["nodes"]
    assert "later:gretchen" in nodes and "stub:gretchen-schwartz" not in nodes
    assert "stub:gretchen-schwartz" in nodes["later:gretchen"].get("referents", [])


def test_a_wrong_schema_or_a_name_nothing_links_is_refused(arch, capsys):
    with pytest.raises(SystemExit, match="cannot be what"):
        cli.main(["stubs", "graduate", str(arch), "Gretchen Schwartz", "--as", "Company"])
    with pytest.raises(SystemExit, match="no link names"):
        cli.main(["stubs", "graduate", str(arch), "Nobody Atall"])
    (arch / layout.VERDICTS).write_text("stub-gretchen-schwartz: NoSuchSchema\n", encoding="utf-8")
    cli.main(["build", str(arch)])
    assert "verdicts.bad-stub" in _out(capsys, "check", str(arch))


def test_reset_removes_stubs(arch, capsys):
    _out(capsys, "stubs", "graduate", str(arch), "Gretchen Schwartz", "--no-build")
    from hydra.cli import reset
    assert reset.main([str(arch), "--only", "stubs", "--no-build"], ask=lambda _p: "", say=lambda *_: None) == 0
    assert not stubs.decided(vd.load(arch)[0])
