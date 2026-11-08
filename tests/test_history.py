"""history: snapshots, branches, restore, merge and compare of the authored files."""
import json
import zipfile

import pytest
import yaml

from hydra import history as H
from hydra import layout
from hydra.cli import init as hinit
from hydra.cli import main as cli
from hydra.cli import pack as hpack

P = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: v if isinstance(v, list) else [v] for k, v in p.items()}}


def write(root, name, recs):
    (root / "collections" / f"{name}.json").write_text(json.dumps(recs, indent=1), encoding="utf-8")


@pytest.fixture
def arch(tmp_path):
    root = hinit.create(tmp_path / "a", name="a", prefix="a")
    write(root, "case", [P("p1", "Person", name="Ann Lee"), P("p2", "Person", name="Bo Grant")])
    return root


def test_snapshot_tracks_authored_files_only(arch):
    sid = H.snapshot(arch, "first")
    files = H.snap(arch, sid)["files"]
    assert "collections/case.json" in files and "hydra.yaml" in files
    (arch / layout.PARSED_DIR).mkdir(parents=True, exist_ok=True)
    (arch / layout.PARSED_DIR / "x.json").write_text("{}", encoding="utf-8")
    assert not any(f.startswith((layout.PARSED_DIR, layout.HISTORY_DIR)) for f in files)
    assert H.snapshot(arch, "again") is None                      # nothing authored changed
    assert not H.dirty(arch)


def test_diff_reads_records_and_decisions(arch):
    H.snapshot(arch, "first")
    write(arch, "case", [P("p1", "Person", name="Ann Lee", birthDate="1970"), P("p3", "Person", name="Cy Vale")])
    (arch / layout.VERDICTS).write_text("merge-abc: rejected\n", encoding="utf-8")
    rows = {r["path"]: r for r in H.diff(arch, "HEAD")}
    assert rows["collections/case.json"]["records"] == {"added": ["p3"], "removed": ["p2"], "changed": ["p1"]}
    assert rows[layout.VERDICTS]["decisions"]["added"] == ["merge-abc"]


def test_branch_switch_restore(arch):
    first = H.snapshot(arch, "first")
    H.switch(arch, "agent", create=True)
    write(arch, "more", [P("x1", "Person", name="Di Moss")])
    H.snapshot(arch, "agent adds more")
    assert (arch / "collections/more.json").is_file()
    H.switch(arch, "main")
    assert not (arch / "collections/more.json").exists()          # main never had it
    write(arch, "case", [])
    with pytest.raises(SystemExit):
        H.switch(arch, "agent")                                     # refuses unsnapshotted changes
    changed, sid = H.restore(arch, "HEAD", ["collections/case.json"])
    assert changed == ["collections/case.json"] and sid is None and not H.dirty(arch)   # dropped, nothing to record
    write(arch, "case", [P("p9", "Person", name="Gil Hart")])
    H.snapshot(arch, "a mistake")
    changed, sid = H.restore(arch, first)
    assert changed == ["collections/case.json"] and sid and not H.dirty(arch)
    assert [r["message"] for r in H.log(arch)][1:] == ["a mistake", "first"]   # restore adds, rewrites nothing
    assert H.resolve(arch, "HEAD~2") == first


def test_merge_record_by_record_and_conflicts(arch):
    H.snapshot(arch, "base")
    H.switch(arch, "agent", create=True)
    write(arch, "case", [P("p1", "Person", name="Ann Lee"), P("p2", "Person", name="Bo Grant", birthDate="1960"),
                         P("p4", "Person", name="Ed Rowe")])
    H.snapshot(arch, "agent")
    H.switch(arch, "main")
    write(arch, "case", [P("p1", "Person", name="Ann Lee", nationality="gb"), P("p2", "Person", name="Bo Grant")])
    H.snapshot(arch, "person")
    res = H.merge(arch, "agent")
    assert res["merged"], res
    recs = {r["id"]: r for r in json.loads((arch / "collections/case.json").read_text(encoding="utf-8"))}
    assert set(recs) == {"p1", "p2", "p4"}
    assert recs["p1"]["properties"].get("nationality") == ["gb"] and recs["p2"]["properties"]["birthDate"] == ["1960"]
    assert len(H.snap(arch, res["snapshot"])["parents"]) == 2
    # the same record changed differently on both sides: a conflict, nothing written
    H.switch(arch, "agent")
    write(arch, "case", [P("p1", "Person", name="Ann Lee", birthDate="1971")])
    H.snapshot(arch, "agent 2")
    H.switch(arch, "main")
    write(arch, "case", [P("p1", "Person", name="Ann Lee", birthDate="1972")])
    H.snapshot(arch, "person 2")
    before = (arch / "collections/case.json").read_bytes()
    res = H.merge(arch, "agent")
    assert not res["merged"] and res["conflicts"]["collections/case.json"] == ["p1"]
    assert (arch / "collections/case.json").read_bytes() == before
    res = H.merge(arch, "agent", prefer="theirs")
    p1 = next(r for r in json.loads((arch / "collections/case.json").read_text(encoding="utf-8")) if r["id"] == "p1")
    assert res["merged"] and p1["properties"]["birthDate"] == ["1971"]


def test_merge_decisions_takes_the_safe_answer(arch):
    v = arch / layout.VERDICTS
    v.write_text("merge-aaa: confirmed\n", encoding="utf-8")
    H.snapshot(arch, "base")
    H.switch(arch, "b", create=True)
    v.write_text("merge-aaa: proposed\nmerge-bbb: confirmed\n", encoding="utf-8")
    H.snapshot(arch, "b")
    H.switch(arch, "main")
    v.write_text("merge-aaa: rejected\ncap-x: Pinned\n", encoding="utf-8")
    H.snapshot(arch, "main")
    res = H.merge(arch, "b")
    assert res["merged"] and res["settled"][layout.VERDICTS] == ["merge-aaa"]
    assert yaml.safe_load(v.read_text(encoding="utf-8")) == {"merge-aaa": "rejected", "merge-bbb": "confirmed",
                                                               "cap-x": "Pinned"}


def test_compare_builds_both_sides(arch):
    H.snapshot(arch, "base")
    write(arch, "case", [P("p1", "Person", name="Ann Lee"), P("p2", "Person", name="Bo Grant"),
                         P("p5", "Person", name="Fay Nolan")])
    res = H.compare(arch, "HEAD")
    assert res["entities"]["added"] == ["Fay Nolan"] and res["entities"]["after"] == res["entities"]["before"] + 1


def test_cli_snapshots_after_writing_commands(arch):
    assert cli(["build", str(arch)]) == 0
    rows = H.log(arch)
    assert len(rows) == 1 and rows[0]["auto"] and rows[0]["message"].startswith("hydra-ctl build")
    assert cli(["build", str(arch)]) == 0
    assert len(H.log(arch)) == 1                                    # nothing authored changed


def test_pack_carries_history_unless_asked(arch, tmp_path):
    H.snapshot(arch, "first")
    out, _, _ = hpack.pack(arch, tmp_path / "with.hydra")
    idx = json.loads(zipfile.ZipFile(out).read(hpack.PACK_INDEX))
    assert idx["history"] and any(f.startswith(layout.HISTORY_DIR) for f in idx["files"])
    out, _, _ = hpack.pack(arch, tmp_path / "without.hydra", with_history=False)
    idx = json.loads(zipfile.ZipFile(out).read(hpack.PACK_INDEX))
    assert "history" not in idx and not any(f.startswith(layout.HISTORY_DIR) for f in idx["files"])
    dest, _ = hpack.unpack(tmp_path / "with.hydra", tmp_path / "opened")
    assert H.log(dest)[0]["message"] == "first"


def test_history_off(arch):
    (arch / "hydra.yaml").write_text((arch / "hydra.yaml").read_text(encoding="utf-8") + "history: off\n",
                                     encoding="utf-8")
    assert H.auto(arch, "x") is None and not (arch / layout.HISTORY_DIR).exists()
