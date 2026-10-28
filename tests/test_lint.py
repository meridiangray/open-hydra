"""lint.py: one issue list, `{level, code, file, where, message}`. Each check is
driven by a small mistake written into a copy of the template."""
import json

import pytest
import yaml


import test_fold as t  # noqa: E402
from _template import copy_template  # noqa: E402
from hydra import build, layout, lint  # noqa: E402

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def arch(tmp_path):
    root = copy_template(tmp_path / "a")
    for f in t.DEMO.glob("*.json"):
        (root / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    return root


def issues(root, code=None):
    got = build.build_archive(root, write=False, now=NOW)["issues"]
    return [i for i in got if code is None or i["code"] == code]


def write(root, rel, text):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def test_the_template_with_the_demo_has_no_errors_or_warnings(arch):
    got = issues(arch)
    assert [i for i in got if i["level"] != "info"] == []
    assert all(set(i) == {"level", "code", "file", "where", "message"} for i in got)


def test_positions(arch):
    write(arch, layout.POSITIONS, "Boss: {bellow: [Leader], titles: [chief]}\n"
                                  "Chief: {outside: true, below: [Leader]}\n")
    assert [i["where"] for i in issues(arch, "positions.shape")] == ["Boss.bellow"]
    assert [i["where"] for i in issues(arch, "positions.outside-with-relations")] == ["Chief"]
    assert any("chief" in i["where"] for i in issues(arch, "positions.title-twice"))


def test_hints(arch):
    write(arch, layout.HINTS, yaml.safe_dump({"hints": [
        {"match": {"notes": {"contains": "(bad"}}, "set": {"badge": "x"}},
        {"match": {"schema": "Persn"}, "set": {"badge": "x"}},
        {"match": {"position": "Nobody"}, "set": {"badge": "x"}},
        {"match": {"colour": "red"}, "set": {"badge": "x"}},
        {"match": {"schema": "Person"}},
        {"match": {"schema": "Person"}, "set": {"badge": "x", "colour": "red"}},
    ], "p-wal": {"badge": "old"}}))
    codes = {(i["code"], i["where"]) for i in issues(arch)}
    assert ("hints.bad-regex", "hints[0]") in codes
    assert ("hints.unknown-schema", "hints[1]") in codes
    assert ("hints.unknown-position", "hints[2]") in codes
    assert ("hints.unknown-property", "hints[3]") in codes
    assert ("hints.incomplete", "hints[4]") in codes
    assert ("hints.shape", "hints.5.set.colour") in codes
    assert ("hints.id-keyed", "p-wal") in codes


def test_direction(arch):
    fam = yaml.safe_load((arch / layout.DIRECTION).read_text(encoding="utf-8"))
    fam["above"].append("notAProperty")
    fam["lateral"].append("NotASchema")
    fam["exclude"].append("Email")
    fam["ignore"].remove("Security.issuer")
    fam["colour"] = "red"
    write(arch, layout.DIRECTION, yaml.safe_dump(fam))
    codes = {(i["code"], i["where"]) for i in issues(arch)}
    assert ("direction.unknown-property", "above.notAProperty") in codes
    assert ("direction.unknown-schema", "lateral.NotASchema") in codes
    assert ("direction.redundant-exclude", "exclude.Email") in codes
    assert ("direction.unclassified", "Security.issuer") in codes
    assert ("direction.shape", "colour") in codes
    assert ("direction.both-ends-above", "Occupancy") in codes


def test_params(arch):
    write(arch, f"{layout.PARAMS_DIR}/Person.param.yaml", "schema: Persn\nmatch: [name, nope]\nweight: 3\n")
    got = {(i["code"], i["level"]) for i in issues(arch) if "Person.param" in i["file"]}
    assert ("params.shape", "error") in got
    assert ("params.reference", "error") in got           # `nope`, skipped
    assert ("params.reference", "warning") in got         # `schema: Persn`


def test_verdicts(arch):
    build.build_archive(arch, now=NOW)
    write(arch, layout.VERDICTS, yaml.safe_dump({
        "merge-0000000000000000": "confirmed",
        "place-1111111111111111": "maybe",
        "cap-hawthorne:p-wal": "Not His Name",
        "cap-nobody:x": "X"}))
    write(arch, ".hydra/review/a/b/verdicts.yaml", yaml.safe_dump({"merge-0000000000000000": "rejected"}))
    codes = {(i["code"], i["where"]) for i in issues(arch)}
    assert ("verdicts.orphan", "merge-0000000000000000") in codes
    assert ("verdicts.bad-value", "place-1111111111111111") in codes
    assert ("verdicts.dead-pin", "cap-hawthorne:p-wal") in codes
    assert ("verdicts.dead-pin", "cap-nobody:x") in codes
    assert ("verdicts.disagree", "merge-0000000000000000") in codes   # the nested file is read


def test_collections_and_manifest(arch):
    write(arch, f"{layout.COLLECTIONS_DIR}/odd.json", json.dumps([
        {"id": "x1", "schema": "Persn", "properties": {"name": ["X"]}},
        {"id": "x2", "schema": "Person", "properties": {"name": ["Y"], "birthDate": ["circa 1990"],
                                                         "colour": ["red"]}}]))
    write(arch, layout.COLLECTIONS_MANIFEST, json.dumps({"collections": {"odd": {"prefix": "Main"}}}))
    codes = {(i["code"], i["where"]) for i in issues(arch)}
    assert ("records.unknown-schema", "x1") in codes
    assert ("records.bad-date", "x2.birthDate") in codes
    assert ("records.unknown-property", "x2.colour") in codes
    assert ("manifest.bad-prefix", "collections.odd.prefix") in codes


def test_issues_are_sorted_errors_first_and_deduplicated():
    a = lint.issue("info", "c", "f", "w", "m")
    b = lint.issue("error", "c", "f", "w", "m")
    assert lint.sort([a, b, a]) == [b, a]


def test_folders_from_the_old_layout_are_reported_not_silently_skipped(arch):
    assert issues(arch, "layout.old-folder") == []
    write(arch, "rules/hierarchy.yaml", "Leader: {}\n")       # where the old layout kept it
    (arch / "parsed").mkdir()
    (arch / "notes").mkdir()                                 # a folder of the person's own: not ours to judge
    got = {i["file"]: i["level"] for i in issues(arch, "layout.old-folder")}
    assert got == {"rules/": "error", "parsed/": "warning"}


def test_hydra_yaml_settings_that_would_be_ignored_are_reported(arch):
    assert [i for i in issues(arch) if i["file"] == layout.MANIFEST] == []      # a fresh archive is clean
    with open(arch / layout.MANIFEST, "a", encoding="utf-8") as f:
        f.write("search: name\ndefaults_off: [direction]\ncolour: red\n")
    got = {i["code"] for i in issues(arch) if i["file"] == layout.MANIFEST}
    assert got == {"archive.bad-search", "archive.bad-default", "archive.unknown-key"}
