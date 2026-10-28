"""The command line: `hydra-ctl <command>` (init, build, check, todo, prefixes, defaults)."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from _paths import HYDRA as ROOT  # noqa: E402

import test_fold as t  # noqa: E402
from hydra import build, cli, layout, resources  # noqa: E402
from hydra.cli import defaults as defaults_cli  # noqa: E402
from hydra.review import ids  # noqa: E402


def test_the_entry_point_lists_the_commands():
    out = subprocess.run([sys.executable, "-m", "hydra"], cwd=ROOT / "src", capture_output=True, text=True)
    assert out.returncode == 0 and all(c in out.stdout for c in cli.COMMANDS)
    bad = subprocess.run([sys.executable, "-m", "hydra", "nope"], cwd=ROOT / "src", capture_output=True, text=True)
    assert bad.returncode == 2 and "unknown command" in bad.stderr
    assert cli.main(["collections/", "--help"]) == 0                   # completed as the archive's folder


def test_init_asks_for_the_name_and_the_prefix_at_a_terminal(tmp_path):
    import yaml
    from hydra.cli import init as init_cli
    meta = lambda d: yaml.safe_load((d / layout.MANIFEST).read_text(encoding="utf-8"))
    answers = iter(["Case: Fairbank #2", "Not OK!", ""])                 # a bad prefix is asked again
    asked = []
    assert init_cli.main([str(tmp_path / "a")], say=lambda _: None,
                         ask=lambda q: asked.append(q) or next(answers)) == 0
    assert asked[0] == "Archive name [a]: " and asked[1].startswith("Id prefix [case-fairbank-2]") and len(asked) == 3
    assert meta(tmp_path / "a")["name"] == "Case: Fairbank #2" and meta(tmp_path / "a")["prefix"] == "case-fairbank-2"
    answers = iter(["", "none"])                                      # Enter: the folder's name; none: no prefix
    init_cli.main([str(tmp_path / "b")], say=lambda _: None, ask=lambda _: next(answers))
    assert meta(tmp_path / "b")["name"] == "b" and "prefix" not in meta(tmp_path / "b")
    init_cli.main([str(tmp_path / "c"), "--name", "given", "--prefix", "gp"], say=lambda _: None,
                  ask=lambda _: pytest.fail("flags were given; init must not ask"))
    assert meta(tmp_path / "c")["name"] == "given" and meta(tmp_path / "c")["prefix"] == "gp"
    with pytest.raises(SystemExit, match="not a usable prefix"):
        init_cli.main([str(tmp_path / "d"), "--prefix", "Bad!"], say=lambda _: None)


def test_the_archive_prefix_is_every_collections_unless_ids_would_collide(tmp_path):
    arch = tmp_path / "a"
    cli.main(["init", str(arch), "--name", "bingo", "--prefix", "bingo"])
    put = lambda name, rows: (arch / layout.COLLECTIONS_DIR / f"{name}.json").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    put("alpha", [{"id": "p1", "schema": "Person", "properties": {"name": ["Ann Lee"]}}])
    put("beta", [{"id": "p2", "schema": "Person", "properties": {"name": ["Bob Ray"]}}])
    put("gamma", [{"id": "p1", "schema": "Person", "properties": {"name": ["Cy Moe"]}}])   # p1 again
    s = build.build_archive(arch)
    assert s["prefixes"] == {"alpha": "bingo", "beta": "bingo", "gamma": "gamma"}
    nodes = json.loads((arch / ".hydra" / "parsed" / "generic.json").read_text())["nodes"]
    assert {"bingo:p1", "bingo:p2", "gamma:p1"} <= set(nodes)        # no record lost to a duplicate id
    assert any(i["code"] == "prefixes.archive-collision" and "gamma" in i["message"] for i in s["issues"])


def test_standard_ftm_id_links_connect_read_as_names_and_export_as_ids(tmp_path, capsys):
    arch = tmp_path / "a"
    cli.main(["init", str(arch), "--name", "a"])
    rows = [{"id": "NK-p1", "schema": "Person", "properties": {"name": ["Ann Lee"]}},
            {"id": "NK-c1", "schema": "Company", "properties": {"name": ["Acme Ltd"]}},
            {"id": "NK-c2", "schema": "Company", "properties": {"name": ["Twin Co"], "registrationNumber": ["111"]}},
            {"id": "NK-c3", "schema": "Company", "properties": {"name": ["Twin Co"], "registrationNumber": ["222"]}},
            {"id": "own-1", "schema": "Ownership", "properties": {"owner": ["NK-p1"], "asset": ["NK-c1"]}},
            {"id": "own-2", "schema": "Ownership", "properties": {"owner": ["NK-p1"], "asset": ["NK-c2", "NK-c3"]}}]
    (arch / layout.COLLECTIONS_DIR / "reg.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    cli.main(["build", str(arch)])
    nodes = json.loads((arch / ".hydra" / "parsed" / "generic.json").read_text())["nodes"]
    assert nodes["reg:NK-c1"]["pid"] == "reg:NK-p1"                   # no setting: the id link connects
    said = {(c["record"], c["prop"], c["value"])
            for c in map(json.loads, (arch / layout.CLAIMS_JSONL).read_text(encoding="utf-8").splitlines())}
    assert ("reg:own-1", "owner", "Ann Lee") in said                  # read in hydra's form: the name
    assert {("reg:own-2", "asset", "reg:NK-c2"), ("reg:own-2", "asset", "reg:NK-c3")} <= said   # two "Twin Co": ids
    assert nodes["reg:NK-c2"]["pid"] == nodes["reg:NK-c3"]["pid"] == "reg:NK-p1"  # ...and both still linked
    out = tmp_path / "x.ftm.jsonl"
    cli.main(["export", str(arch), "--format", "ftm", "-o", str(out)])
    own = next(e for e in map(json.loads, out.read_text(encoding="utf-8").splitlines()) if e["id"] == "reg:own-1")
    assert own["properties"]["owner"] == ["reg:NK-p1"]               # standard FtM out: the record id


def test_every_command_is_in_exactly_one_group():
    names = [n for group in cli.GROUPS.values() for n in group]
    assert len(names) == len(set(names)) == len(cli.COMMANDS)
    assert all(t in cli.usage() for t in cli.GROUPS)


def test_init_build_todo_check(tmp_path, capsys):
    arch = tmp_path / "case"
    assert cli.main(["init", str(arch), "--name", "case-one"]) == 0
    assert "name: case-one" in (arch / layout.MANIFEST).read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="already an archive"):     # init only creates
        cli.main(["init", str(arch)])
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="not empty"):
        cli.main(["init", str(other)])
    for f in t.DEMO.glob("*.json"):
        (arch / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    capsys.readouterr()
    assert cli.main(["todo", str(arch)]) == 0                       # no build yet: warns, builds, answers
    assert "building it now" in capsys.readouterr().err
    assert (arch / layout.BUILD_YAML).is_file()
    assert cli.main(["build", str(arch)]) == 0
    capsys.readouterr()
    assert cli.main(["todo", str(arch), "--format", "json"]) == 0
    todo = json.loads(capsys.readouterr().out)
    assert len(todo["merges"]) == 14 and todo["merges"][0]["id"].startswith("merge-")
    assert cli.main(["todo", str(arch), "--list", "references"]) == 0
    assert "ref-" in capsys.readouterr().out
    assert cli.main(["check", str(arch)]) == 0                      # no errors
    (arch / layout.HINTS).write_text("hints:\n  - match: {notes: {contains: '(bad'}}\n    set: {badge: x}\n",
                                     encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["check", str(arch)]) == 1                      # an error now
    assert "hints.bad-regex" in capsys.readouterr().out


def test_check_lists_what_only_the_last_build_found_while_it_stands(tmp_path, capsys):
    """`check` never builds, but while the last build stands its own issues are
    listed and counted too: a duplicate id is an error only a build sees."""
    P = {"id": "x", "schema": "Person", "properties": {"name": ["Ann Lee"]}}
    arch = _built(tmp_path, [P, {**P, "properties": {"name": ["Bob Ray"]}}])
    capsys.readouterr()
    assert cli.main(["check", str(arch)]) == 1                      # the build's error counts
    out = capsys.readouterr().out
    assert re.search(r"records\.duplicate-id +error +build +1", out)
    assert re.search(r"errors +0 +1", out)                          # check 0, build 1
    assert cli.main(["check", str(arch), "--format", "json"]) == 1
    assert any(i.get("from") == "build" and i["code"] == "records.duplicate-id"
               for i in json.loads(capsys.readouterr().out))
    import os, time
    later = time.time() + 60                                        # a collection changed: the build no longer stands
    os.utime(arch / layout.COLLECTIONS_DIR / "c.json", (later, later))
    assert cli.main(["check", str(arch)]) == 0
    out = capsys.readouterr().out
    assert not re.search(r" build +\d+ +", out.split("errors")[0]) and "old build" in out


def test_searches_can_leave_out_free_text_or_everything_but_names(tmp_path, capsys):
    """`all` reads every field, `--no-text` leaves out notes and the like (a city
    still counts), `--names` leaves names and ids; `search:` in hydra.yaml sets it."""
    from hydra.cli import node
    arch = _built(tmp_path)
    ids = lambda mode: {h["id"] for h in node.find(arch, "alderton", limit=0, search=mode)}
    every, no_text, names = ids("all"), ids("no-text"), ids("names")
    assert names < no_text < every
    assert "dce:p-merkert" in every and "dce:p-merkert" not in no_text          # only his notes say it
    assert "operations:addr-ald" in no_text and "operations:addr-ald" not in names   # a city is not free text
    capsys.readouterr()
    cli.main(["tree", str(arch), "person", "alderton"])
    assert "Gordon Merkert" in capsys.readouterr().out
    cli.main(["tree", str(arch), "person", "alderton", "--no-text"])
    assert capsys.readouterr().out == "no record matches\n"
    (arch / layout.MANIFEST).write_text((arch / layout.MANIFEST).read_text(encoding="utf-8") + "search: no-text\n",
                                        encoding="utf-8")
    cli.main(["claims", str(arch), "person", "alderton"])                  # the archive's default now
    assert "no entity matches" in capsys.readouterr().out


def _built(tmp_path, recs=None):
    arch = tmp_path / "ans"
    cli.main(["init", str(arch)])
    if recs is None:
        for f in t.DEMO.glob("*.json"):
            (arch / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    else:
        (arch / layout.COLLECTIONS_DIR / "c.json").write_text(json.dumps(recs), encoding="utf-8")
    cli.main(["build", str(arch)])
    return arch


def _todo(arch, capsys):
    capsys.readouterr()
    cli.main(["todo", str(arch), "--format", "json"])
    return json.loads(capsys.readouterr().out)


def test_answer_writes_one_line_keeps_the_rest_and_rebuilds(tmp_path, capsys):
    arch = _built(tmp_path)
    todo = _todo(arch, capsys)
    merge = todo["merges"][0]["row"]
    place = todo["placements"][0]["id"]
    vfile = arch / layout.VERDICTS
    header = vfile.read_text(encoding="utf-8")
    assert cli.main(["answer", str(arch), merge["id"], "confirm"]) == 0
    assert cli.main(["answer", str(arch), place, "reject"]) == 0
    text = vfile.read_text(encoding="utf-8")
    assert text.startswith(header.rstrip("\n"))                       # comments kept
    import yaml
    doc = yaml.safe_load(text)
    assert doc[merge["id"]] == {"status": "confirmed", "basis": merge["basis"]}
    assert doc[place] == "rejected"
    after = _todo(arch, capsys)
    assert place not in {r["id"] for r in after["placements"]}
    assert cli.main(["answer", str(arch), place, "clear", "--no-build"]) == 0
    assert place not in (yaml.safe_load(vfile.read_text(encoding="utf-8")) or {})
    with pytest.raises(SystemExit, match="no row"):
        cli.main(["answer", str(arch), "merge-0000000000000000", "confirm"])
    with pytest.raises(SystemExit, match="confirm, reject or clear"):
        cli.main(["answer", str(arch), merge["id"], "maybe"])


def test_a_reference_is_answered_by_candidate_number(tmp_path, capsys):
    arch = _built(tmp_path)
    ref = _todo(arch, capsys)["references"][0]["row"]
    assert cli.main(["answer", str(arch), ref["id"], "1", "--no-build"]) == 0
    import yaml
    assert yaml.safe_load((arch / layout.VERDICTS).read_text(encoding="utf-8"))[ref["id"]] == \
        ref["candidates"][0]["id"]


def test_a_confirmed_merge_comes_back_when_its_evidence_changes(tmp_path, capsys):
    recs = [{"id": "a", "schema": "Person", "properties": {"name": ["Ann Lee"]}},
            {"id": "b", "schema": "Person", "properties": {"name": ["Ann Lee Smith"]}}]
    arch = _built(tmp_path, recs)
    row = _todo(arch, capsys)["merges"][0]["row"]
    cli.main(["answer", str(arch), row["id"], "confirm"])
    assert _todo(arch, capsys)["merges"] == [] and _todo(arch, capsys)["stale"] == []
    recs[1]["properties"]["birthDate"] = ["1980"]                     # new evidence on one side
    (arch / layout.COLLECTIONS_DIR / "c.json").write_text(json.dumps(recs), encoding="utf-8")
    cli.main(["build", str(arch)])
    stale = _todo(arch, capsys)["stale"]
    assert [r["id"] for r in stale] == [row["id"]] and stale[0]["status"] == "confirmed-stale"


def test_activate_makes_dir_optional(tmp_path, capsys, monkeypatch):
    arch = _built(tmp_path)
    work = tmp_path / "work"
    (work / "deeper").mkdir(parents=True)
    monkeypatch.chdir(work)
    assert cli.main(["activate", str(arch)]) == 0
    monkeypatch.chdir(work / "deeper")
    capsys.readouterr()
    assert cli.main(["todo"]) == 0 and "merges" in capsys.readouterr().out      # no <dir>
    assert cli.main(["tree"]) == 0
    assert cli.main(["deactivate"]) == 0
    with pytest.raises(SystemExit, match="no archive given"):
        cli.main(["todo"])


def test_a_folder_that_is_not_an_archive_is_refused_and_nothing_is_written(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    (plain / layout.COLLECTIONS_DIR).mkdir(parents=True)
    for f in t.DEMO.glob("*.json"):                     # records, but no hydra.yaml
        (plain / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    for cmd in ("build", "details", "review", "todo", "check", "pack", "reset"):
        with pytest.raises(SystemExit, match="is not an archive"):
            cli.main([cmd, str(plain)])
    assert sorted(p.name for p in plain.iterdir()) == [layout.COLLECTIONS_DIR]
    arch = tmp_path / "gone"
    cli.main(["init", str(arch)])
    monkeypatch.chdir(tmp_path)
    assert cli.main(["activate", str(arch)]) == 0
    (arch / layout.MANIFEST).unlink()                   # the active archive stops being one
    with pytest.raises(SystemExit, match="no longer an archive"):
        cli.main(["todo"])


def test_building_an_empty_archive_says_what_to_do(tmp_path):
    arch = tmp_path / "new"
    cli.main(["init", str(arch)])
    with pytest.raises(SystemExit, match="no records to build from yet"):
        cli.main(["build", str(arch)])


def test_node_find_ranks_typos_types_and_ids(tmp_path, capsys):
    arch = _built(tmp_path)
    from hydra.cli import node
    top = node.find(arch, "wallace wrigt", limit=2)
    assert {h["id"] for h in top} == {"hawthorne:p-wal", "dce:p-waljr"}
    people = node.find(arch, "hawthorne", kind="person")
    assert {h["id"] for h in people[:2]} == {"dce:p-hawthorne-dce", "hawthorne:p-wal"}   # named so, first
    hal = next(h for h in people if h["id"] == "dce:p-hal")                              # then a field naming him
    assert hal["matched"]["field"] not in node.NAMES and hal["score"] < people[1]["score"]
    assert all(h["schema"] == "Person" for h in people)
    exact = node.find(arch, "p-wal", field="id", limit=1)[0]
    assert exact["id"] == "hawthorne:p-wal" and exact["score"] == 1.0
    assert node.find(arch, "zzzz qqqq") == []
    capsys.readouterr()
    assert cli.main(["node", "find", str(arch), "sandovel", "--limit", "2"]) == 0
    assert "Sandoval" in capsys.readouterr().out
    assert cli.main(["node", "find", str(arch), "PERSON", "hawthorne", "--format", "json"]) == 0      # a type word, any case
    worded = json.loads(capsys.readouterr().out)
    assert cli.main(["node", "find", str(arch), "hawthorne", "--type", "Person", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == worded


def _review(arch, keys, *extra):
    from hydra.cli import review
    out, it = [], iter(keys)
    review.main([str(arch), *extra], ask=lambda _p: next(it), say=out.append)
    return "\n".join(str(x) for x in out)


def _verdicts(arch):
    import yaml
    return yaml.safe_load((arch / layout.VERDICTS).read_text(encoding="utf-8")) or {}


def test_review_answers_a_group_undoes_and_rebuilds_once(tmp_path, capsys):
    arch = _built(tmp_path)
    merges = _todo(arch, capsys)["merges"]
    group = next(r["row"]["group"] for r in merges if r["row"].get("group"))
    none = str(sum(1 for r in merges if r["row"].get("group") == group) + 1)   # "none of these" is the last number
    # skip until the first group question, then pick 1, undo, pick none, quit
    out = _review(arch, ["", "", "1", "u", none, "q"], "--only", "merges")
    v = _verdicts(arch)
    assert "Rebuilt " in out and "undone" in out
    answered = {k: x for k, x in v.items() if k.startswith("merge-")}
    assert answered and all(x["status"] == "rejected" and x["basis"] for x in answered.values())
    assert group  # the demo has groups


def test_review_none_on_a_reference_is_not_asked_again(tmp_path, capsys):
    arch = _built(tmp_path)
    before = _todo(arch, capsys)["references"]
    none = str(len(before[0]["row"].get("candidates") or []) + 1)     # "none of these" is the last number
    _review(arch, [none, "q"], "--only", "references")
    assert _verdicts(arch)[before[0]["id"]] == "none"
    after = _todo(arch, capsys)["references"]
    assert before[0]["id"] not in {r["id"] for r in after} and len(after) == len(before) - 1


def test_review_accept_all_from_a_rule(tmp_path, capsys):
    arch = _built(tmp_path)
    rows = _todo(arch, capsys)["placements"]                    # in the order review asks them
    crit = [r["row"]["criteria"] for r in rows]
    at = next(i for i, c in enumerate(crit) if c.startswith("rules:") and crit.count(c) > 1)
    rule = crit[at]
    same = [r["id"] for r in rows if r["row"]["criteria"] == rule]
    out = _review(arch, ["?"] * at + ["a", "q"], "--only", "placements", "--no-build")
    v = _verdicts(arch)
    assert all(v[k] == "confirmed" for k in same) and f"keep all {len(same)} placed by {rule}" in out


def test_reset_warns_backs_up_and_needs_enter(tmp_path, capsys):
    arch = _built(tmp_path)
    todo_ = _todo(arch, capsys)
    cli.main(["answer", str(arch), todo_["merges"][0]["id"], "reject", "--no-build"])
    cli.main(["answer", str(arch), todo_["placements"][0]["id"], "reject", "--no-build"])
    from hydra.cli import reset
    out = []
    assert reset.main([str(arch), "--no-build"], ask=lambda _p: "no", say=out.append) == 1
    assert "cancelled" in out[-1] and len(_verdicts(arch)) == 2         # nothing changed
    out = []
    assert reset.main([str(arch), "--only", "placements", "--no-build"], ask=lambda _p: "", say=out.append) == 0
    v = _verdicts(arch)
    assert list(v) == [todo_["merges"][0]["id"]]                       # only placements went
    assert list((arch / ".hydra" / "review").glob("verdicts.yaml.*.bak"))
    assert "1 placements" in out[0]


def test_review_shows_what_a_group_option_disagrees_on(tmp_path):
    P = lambda i, **p: {"id": i, "schema": "Person", "properties": {k: [v] for k, v in p.items()}}
    arch = tmp_path / "g"
    cli.main(["init", str(arch)])
    for c, r in (("registry", P("a", name="Jonathan Smith", passportNumber="P1", birthDate="1970-01-01")),
                 ("leaks", P("b", name="Jon Smyth", passportNumber="P1", birthDate="1970-01-01")),
                 ("press", P("c", name="J. Smithe", passportNumber="P1", birthDate="1971"))):
        (arch / layout.COLLECTIONS_DIR / f"{c}.json").write_text(json.dumps([r]), encoding="utf-8")
    cli.main(["build", str(arch)])
    out = _review(arch, ["\t", "q"], "--no-build")
    first, then = out.split("Tab / Shift+Tab", 1)
    assert "[conflicting fields]" in first                    # a clash: it opens on what has to be decided
    assert "[all fields]" in then.split("Tab / Shift+Tab")[0]  # Tab: back to every field
    shown = first.split("Which is better?")[0] if "Which is better?" in first else first
    assert re.search(r"┌─ Merge with ─+┐\n +│ press:c   Person +│\n +│    birthDate +1971 +│\n", shown)   # boxed
    assert len(re.findall(r"birthDate +≠ 1970-01-01", shown)) == 2
    assert "passportNumber" not in shown


def test_review_asks_which_is_better_and_a_different_parent_moves_the_record(tmp_path):
    """Two placement questions, each answered with option 2: Loyal Provisions
    moves from one owner to the other, and Hugo from under the leader (a
    position rule) to the consortium he is a member of."""
    arch = tmp_path / "w"
    cli.main(["init", str(arch), "--name", "w"])
    R = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: [v] for k, v in p.items()}}
    rows = [R("jericho", "Organization", name="Juárez Consortium"), R("elias", "Person", name="Elias Vaughn"),
            R("hugo", "Person", name="Hugo Sandoval"),
            R("m1", "Membership", member="elias", organization="jericho", role="leader"),
            R("m2", "Membership", member="hugo", organization="jericho", role="member"),
            R("lph", "Company", name="Loyal Provisions"), R("meridian", "Company", name="Meridian Electrotech"),
            R("gid", "Person", name="Gideon Fairbank"),
            R("o1", "Ownership", owner="meridian", asset="lph", role="parent company"),
            R("o2", "Ownership", owner="gid", asset="lph", role="co-founder")]
    (arch / layout.COLLECTIONS_DIR / "w.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    cli.main(["build", str(arch)])
    pid = lambda i: json.loads((arch / ".hydra" / "parsed" / "declared.json").read_text())["nodes"][i].get("pid")
    before = {i: pid(i) for i in ("w:lph", "w:hugo")}
    assert before["w:hugo"] == "w:elias"                            # drawn by the position rules
    out = _review(arch, ["2", "2", "q"], "--only", "placements")
    assert out.count("Which is better?") == 2 and "rules: " in out and "now" in out
    assert "w:o1   Ownership" in out and "w:o2   Ownership" in out          # each parent as its relationship record
    assert pid("w:hugo") == "w:jericho"                               # the rule no longer puts him back
    assert pid("w:lph") != before["w:lph"] and pid("w:lph") in {"w:gid", "w:meridian"}


# ---- prefixes and defaults -------------------------------------------------------


def _rows(arch):
    return {json.loads(l)["id"]: json.loads(l) for rel in (layout.IDENTICAL_JSONL, layout.LEDGER_JSONL)
            for l in (arch / rel).read_text(encoding="utf-8").splitlines() if l.strip()}


def test_tags_set_refuses_to_orphan_decisions_and_rekey_keeps_them(tmp_path, capsys):
    """A confirmed merge, placement and caption filed under `hawthorne:` ids:
    renaming the prefix refuses without --rekey; with it, all three are re-filed under
    `hb:` ids and still apply after the rebuild, with no orphan reported."""
    import yaml
    arch = _built(tmp_path)
    place = next(r for r in _rows(arch).values() if r["rel"] == "placedUnder"
                 and r["status"] == "proposed" and r["sub"].startswith("hawthorne:"))
    merge = next(r for r in _rows(arch).values() if r["rel"] == "sameAs"
                 and {r["acap"], r["bcap"]} == {"Hawthorne", "Wallace Hollis Wright"})
    assert cli.main(["answer", str(arch), place["id"], "confirm", "--no-build"]) == 0
    assert cli.main(["answer", str(arch), merge["id"], "confirm"]) == 0
    assert _rows(arch)[merge["id"]]["status"] == "confirmed"
    rid, name = "hawthorne:p-wal", "Hawthorne"                # a name the merge gave it
    assert cli.main(["answer", str(arch), f"cap-{rid}", name]) == 0
    capsys.readouterr()
    assert cli.main(["collections", "prefix", str(arch), "hawthorne", "hb"]) == 1
    assert "--rekey" in capsys.readouterr().out
    assert json.loads((arch / layout.COLLECTIONS_MANIFEST).read_text())["collections"]["hawthorne"]["prefix"] == "hawthorne"
    assert cli.main(["collections", "prefix", str(arch), "hawthorne", "hb", "--rekey"]) == 0
    assert "3 of 3 rewritten decisions found their rows" in capsys.readouterr().out
    doc = yaml.safe_load((arch / layout.VERDICTS).read_text(encoding="utf-8"))
    hb = rid.replace("hawthorne:", "hb:", 1)
    assert [r["status"] for r in _rows(arch).values() if r["rel"] == "sameAs"
            and {r["a"], r["b"]} == {merge["a"].replace("hawthorne:", "hb:", 1),
                                     merge["b"].replace("hawthorne:", "hb:", 1)}] == ["confirmed"]
    assert doc[f"cap-{hb}"] == name and f"cap-{rid}" not in doc
    assert json.loads((arch / ".hydra" / "parsed" / "declared.json").read_text(encoding="utf-8"))["nodes"][hb]["caption"] == name
    moved = ids.place_key(place["sub"].replace("hawthorne:", "hb:", 1), place["sup"].replace("hawthorne:", "hb:", 1))
    assert _rows(arch)[moved]["status"] == "confirmed"
    built = yaml.safe_load((arch / layout.BUILD_YAML).read_text(encoding="utf-8"))
    assert not [i for i in built["issues"] if i["code"].startswith("verdicts.")]
    with pytest.raises(SystemExit, match="already the prefix of"):
        cli.main(["collections", "prefix", str(arch), "dce", "hb"])
    with pytest.raises(SystemExit, match="not a usable prefix"):
        cli.main(["collections", "prefix", str(arch), "dce", "Not OK"])


def test_defaults_off_on_restore_and_status(tmp_path, capsys):
    import yaml
    arch = _built(tmp_path)
    positioned = lambda: sum(1 for n in json.loads((arch / ".hydra" / "parsed" / "generic.json").read_text())["nodes"].values()
                             if n.get("position"))
    before = positioned()
    assert before
    assert cli.main(["defaults", "off", str(arch), "generic"]) == 0
    assert yaml.safe_load((arch / layout.MANIFEST).read_text())["defaults_off"] == ["generic"]
    cli.main(["build", str(arch)])
    assert positioned() == 0                                         # read as empty
    assert (arch / layout.DEFAULT_POSITIONS).is_file()                         # but kept
    with pytest.raises(SystemExit, match="cannot be switched off"):
        cli.main(["defaults", "off", str(arch), "direction"])
    assert cli.main(["defaults", "on", str(arch)]) == 0
    assert "defaults_off" not in (arch / layout.MANIFEST).read_text()
    cli.main(["build", str(arch)])
    assert positioned() == before
    (arch / layout.HINTS).write_text("hints: []\n", encoding="utf-8")
    (arch / layout.PARAMS_DIR / "Person.param.yaml").unlink()
    capsys.readouterr()
    assert cli.main(["defaults", str(arch)]) == 0
    out = capsys.readouterr().out
    assert "hints      changed" in out and "params     missing" in out
    assert defaults_cli.main(["restore", str(arch), "hints", "params"], ask=lambda _: "no", say=lambda _: None) == 1
    assert (arch / layout.HINTS).read_text() == "hints: []\n"         # cancelled: untouched
    assert cli.main(["defaults", "restore", str(arch), "hints", "params", "--yes"]) == 0
    assert list((arch / layout.RULES_DIR).glob("hints.yaml.*.bak"))
    assert all(resources.default_state(arch, n)["state"] == "default" for n in ("hints", "params"))


def test_a_confirmed_rule_placement_holds_when_a_caption_changes(tmp_path, capsys):
    """Paul Kemp is placed by the position rules alone, under Jordan (Wal is the
    other Leader). Confirmed, it is a pin: making Wal's caption `Hawthorne`
    (which sorts before Jordan) changes a label only, never the confirmed parent."""
    arch = _built(tmp_path)
    place = next(r for r in _rows(arch).values() if r["rel"] == "placedUnder"
                 and r["subcap"] == "Paul Kemp")
    assert place["sup"] == "hawthorne:p-jordan" and place["criteria"].startswith("rules:")
    merge = next(r for r in _rows(arch).values() if r["rel"] == "sameAs"
                 and {r["acap"], r["bcap"]} == {"Hawthorne", "Wallace Hollis Wright"})
    for key, value in ((place["id"], "confirm"), (merge["id"], "confirm"), ("cap-hawthorne:p-wal", "Hawthorne")):
        assert cli.main(["answer", str(arch), key, value]) == 0
    now = _rows(arch)[place["id"]]
    assert (now["sup"], now["status"], now.get("stale")) == ("hawthorne:p-jordan", "confirmed", None)
    nodes = json.loads((arch / ".hydra" / "parsed" / "declared.json").read_text(encoding="utf-8"))["nodes"]
    assert nodes[place["sub"]]["pid"] == "hawthorne:p-jordan"              # the tree, not a carried-over row


# ---- pack / unpack -------------------------------------------------------------


def test_pack_is_reproducible_and_round_trips_to_the_same_build(tmp_path, capsys):
    arch = _built(tmp_path)
    (arch / layout.VERDICTS).with_name("verdicts.yaml.1.bak").write_text("x: 1\n", encoding="utf-8")
    a, b = tmp_path / "a.hydra", tmp_path / "b.hydra"
    assert cli.main(["pack", str(arch), "-o", str(a)]) == 0
    assert cli.main(["pack", str(arch), "-o", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()                          # same archive, same bytes
    with pytest.raises(SystemExit, match="exists"):
        cli.main(["pack", str(arch), "-o", str(a)])
    import zipfile
    names = zipfile.ZipFile(a).namelist()
    assert "hydra.yaml" in names and "hydra-pack.json" in names
    assert ".hydra/parsed/build.yaml" in names                              # the build goes in by default
    assert not [n for n in names if n.endswith(".bak")]
    copy = tmp_path / "copy"
    assert cli.main(["unpack", str(a), str(copy)]) == 0
    cli.main(["build", str(copy)])
    cli.main(["build", str(arch)])
    for f in sorted((arch / ".hydra" / "parsed").iterdir()):
        if f.name not in ("build.yaml", ".gitkeep"):
            assert (copy / ".hydra" / "parsed" / f.name).read_bytes() == f.read_bytes(), f.name
    with pytest.raises(SystemExit, match="not empty"):
        cli.main(["unpack", str(a), str(copy)])
    p = tmp_path / "p.hydra"
    assert cli.main(["pack", str(arch), "-o", str(p), "--no-parsed"]) == 0
    assert not any(n.startswith(".hydra/parsed/") for n in zipfile.ZipFile(p).namelist())


def _repack(src, dst, change):
    """Copy a pack, letting `change(name, data)` return new data, or a (name, data) to add."""
    import zipfile
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for i in zin.infolist():
            zout.writestr(i.filename, change(i.filename, zin.read(i.filename)))
        extra = change(None, None)
        if extra:
            zout.writestr(*extra)


def test_unpack_refuses_escaping_tampered_and_foreign_files(tmp_path):
    arch = _built(tmp_path)
    good = tmp_path / "good.hydra"
    cli.main(["pack", str(arch), "-o", str(good)])
    cases = {
        "escape": (lambda n, d: d if n else ("../evil.txt", b"x"), "outside the archive"),
        "tamper": (lambda n, d: (d + b"\n# edited" if n == "hydra.yaml" else d) if n else None, "damaged"),
        "unlisted": (lambda n, d: d if n else ("collections/extra.json", b"[]"), "does not match"),
    }
    for label, (change, msg) in cases.items():
        bad = tmp_path / f"{label}.hydra"
        _repack(good, bad, change)
        dest = tmp_path / f"out-{label}"
        with pytest.raises(SystemExit, match=msg):
            cli.main(["unpack", str(bad), str(dest)])
        assert not dest.exists()                                     # nothing left behind
    assert not (tmp_path / "evil.txt").exists()
    notzip = tmp_path / "notzip.hydra"
    notzip.write_text("hello", encoding="utf-8")
    with pytest.raises(SystemExit, match="not a .hydra pack"):
        cli.main(["unpack", str(notzip), str(tmp_path / "out-notzip")])


def test_a_hydra_file_is_read_in_place_opened_by_init_and_refused_by_writers(tmp_path, capsys):
    arch = _built(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    full, bare = share / "case.hydra", share / "bare.hydra"
    cli.main(["pack", str(arch), "-o", str(full)])
    cli.main(["pack", str(arch), "-o", str(bare), "--no-parsed"])
    capsys.readouterr()
    # read in place: same answers as the live archive, nothing written beside the file
    cli.main(["todo", str(arch), "--format", "json"])
    live = json.loads(capsys.readouterr().out)
    assert cli.main(["todo", str(full), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == live
    assert cli.main(["tree", str(full)]) == 0
    assert cli.main(["claims", "summary", str(full)]) == 0
    capsys.readouterr()
    assert cli.main(["todo", str(bare), "--format", "json"]) == 0              # no build inside: warns, builds aside
    got = capsys.readouterr()
    assert json.loads(got.out) == live and "bare.hydra carries no build" in got.err
    assert sorted(p.name for p in share.iterdir()) == ["bare.hydra", "case.hydra"]
    # writers refuse a pack
    for argv in (["build", str(full)], ["review", str(full)], ["reset", str(full), "--yes"],
                 ["answer", str(full), "merge-x", "confirm"], ["defaults", "off", str(full)]):
        with pytest.raises(SystemExit, match="open it first: init"):
            cli.main(argv)
    # init opens beside the file; a pack without its build is built on opening
    assert cli.main(["init", str(bare)]) == 0
    opened = share / "bare"
    assert resources.is_archive(opened) and (opened / layout.BUILD_YAML).is_file()
    with pytest.raises(SystemExit, match="not empty"):
        cli.main(["init", str(bare)])
    with pytest.raises(SystemExit, match="carries its own name"):
        cli.main(["init", str(full), "--name", "x"])


def test_details_reads_a_folder_or_a_pack_without_building_or_unpacking(tmp_path, capsys, monkeypatch):
    arch = _built(tmp_path)
    pack_file = tmp_path / "case.hydra"
    cli.main(["pack", str(arch), "-o", str(pack_file)])
    capsys.readouterr()
    assert cli.main(["details", str(arch), "--format", "json"]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["records"] == 244 and live["entities"] < 244          # merging joined some
    assert live["schemas"]["Person"]["records"] >= live["schemas"]["Person"]["entities"] > 0
    assert live["open"]["merges"] == 14 and live["newer_than_build"] == []
    from hydra.cli import pack as pack_mod
    monkeypatch.setattr(pack_mod, "unpack", lambda *a, **k: pytest.fail("details must not unpack"))
    assert cli.main(["details", str(pack_file), "--format", "json"]) == 0
    packed = json.loads(capsys.readouterr().out)
    assert packed["pack"]["with_build"] and packed["records"] == live["records"] and packed["open"] == live["open"]
    import os, time
    later = time.time() + 60
    os.utime(arch / layout.COLLECTIONS_DIR / "hawthorne.json", (later, later))
    assert cli.main(["details", str(arch)]) == 0
    assert re.search(r"changed +collections/hawthorne\.json", capsys.readouterr().out)
    fresh = tmp_path / "fresh"
    cli.main(["init", str(fresh)])
    capsys.readouterr()
    assert cli.main(["details", str(fresh)]) == 0
    assert re.search(r"built +not yet", capsys.readouterr().out)
    assert not (fresh / layout.BUILD_YAML).exists()                    # details never builds


# ---- export --------------------------------------------------------------------


def test_export_ftm_csv_graphml_agree_and_read_a_pack(tmp_path, capsys):
    import csv
    import xml.etree.ElementTree as ET
    from hydra import schema
    arch = _built(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    snapshot = lambda: {p.relative_to(arch).as_posix(): p.read_bytes() for p in arch.rglob("*") if p.is_file()}
    before = snapshot()
    assert not (arch / ".hydra" / "parsed" / "entities.jsonl").exists()          # the build writes no entity file
    assert cli.main(["export", str(arch), "--format", "ftm", "-o", str(out / "e.jsonl")]) == 0
    ents = [json.loads(l) for l in (out / "e.jsonl").read_text(encoding="utf-8").splitlines()]
    ids_ = {e["id"] for e in ents}
    schema.load(root=arch)
    from hydra.ingest import FTM_RENAMES
    for e in ents:                                                   # valid FtM: known schema, known props
        known = set(schema.resolve(e["schema"])["props"])
        known = (known - set(FTM_RENAMES.values())) | {f for f, ours in FTM_RENAMES.items() if ours in known}
        assert set(e["properties"]) <= known, (e["id"], set(e["properties"]) - known)
        assert "sources" not in e["properties"]                      # FtM's own name in an FtM export
    m = next(e for e in ents if e["id"] == "consortium:rel-ct1")
    assert m["properties"]["member"] == ["consortium:p-elias"] and m["properties"]["organization"][0] in ids_
    assert cli.main(["export", str(arch), "--format", "csv", "-o", str(out / "g")]) == 0
    nodes = list(csv.DictReader((out / "g" / "nodes.csv").open(encoding="utf-8")))
    edges = list(csv.DictReader((out / "g" / "edges.csv").open(encoding="utf-8")))
    node_ids = {n["id"] for n in nodes}
    assert node_ids <= ids_ and all(e["source"] in node_ids and e["target"] in node_ids for e in edges)
    kinds = {e["type"] for e in edges}
    assert {"Membership", "placedUnder", "sameAs"} <= kinds
    assert all(e["status"] for e in edges if e["type"] in ("placedUnder", "sameAs"))
    assert cli.main(["export", str(arch), "--format", "graphml", "-o", str(out / "g.graphml")]) == 0
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    g = ET.parse(out / "g.graphml").getroot().find("g:graph", ns)
    assert len(g.findall("g:node", ns)) == len(nodes) and len(g.findall("g:edge", ns)) == len(edges)
    with pytest.raises(SystemExit, match="exists"):
        cli.main(["export", str(arch), "--format", "graphml", "-o", str(out / "g.graphml")])
    assert snapshot() == before                                       # export wrote nothing into the archive
    pack_file = tmp_path / "case.hydra"
    cli.main(["pack", str(arch), "-o", str(pack_file)])
    assert cli.main(["export", str(pack_file), "--format", "csv", "-o", str(out / "p")]) == 0
    assert (out / "p" / "edges.csv").read_bytes() == (out / "g" / "edges.csv").read_bytes()


def test_hydra_ftm_keeps_names_and_goes_back_into_a_collection(tmp_path, capsys):
    """`ftm` writes ids in link fields, `hydra-ftm` the names the records wrote.
    A hydra-ftm export dropped into a new archive builds with every link
    resolving to the same records, and no id read as a literal."""
    import yaml
    arch = _built(tmp_path)
    capsys.readouterr()
    assert cli.main(["export", str(arch), "--format", "ftm", "-o", str(tmp_path / "std.jsonl")]) == 0
    assert "ftm schema" in capsys.readouterr().out
    assert cli.main(["export", str(arch), "--format", "hydra-ftm", "-o", str(tmp_path / "hyd.jsonl")]) == 0
    read = lambda f: {e["id"]: e for e in map(json.loads, (tmp_path / f).read_text(encoding="utf-8").splitlines())}
    std, hyd = read("std.jsonl"), read("hyd.jsonl")
    assert std["consortium:rel-ct1"]["properties"]["member"] == ["consortium:p-elias"]
    assert hyd["consortium:rel-ct1"]["properties"]["member"] == ["Elias Vaughn"]
    again = tmp_path / "again"
    cli.main(["init", str(again)])
    (again / layout.COLLECTIONS_DIR / "merged.json").write_text(
        (tmp_path / "hyd.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    cli.main(["build", str(again)])
    built = yaml.safe_load((again / layout.BUILD_YAML).read_text(encoding="utf-8"))
    assert not [i for i in built["issues"] if i["code"] == "records.literal-id"]
    assert cli.main(["export", str(again), "--format", "ftm", "-o", str(tmp_path / "std2.jsonl")]) == 0
    std2 = read("std2.jsonl")
    assert std2["consortium:rel-ct1"]["properties"]["member"] == ["consortium:p-elias"]
    links = lambda d: {(k, p, tuple(v)) for k, e in d.items() for p, v in e["properties"].items()
                       if p in ("member", "organization", "owner", "asset", "director", "employee", "employer")}
    assert links(std2) == links(std)


def test_export_leaves_open_merge_questions_out_of_an_unbuilt_archive(tmp_path, capsys):
    """Open `sameAs` questions are review state: a built archive exports them, an
    unbuilt one (or a pack without its build) does not, and says so."""
    import csv
    arch = tmp_path / "raw"
    cli.main(["init", str(arch)])
    for f in t.DEMO.glob("*.json"):
        (arch / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    capsys.readouterr()
    assert cli.main(["export", str(arch), "--format", "csv", "-o", str(tmp_path / "raw-g")]) == 0
    out = capsys.readouterr().out
    assert "open merges" in out and "left out" in out
    kinds = lambda d: {e["type"] for e in csv.DictReader((tmp_path / d / "edges.csv").open(encoding="utf-8"))}
    assert "sameAs" not in kinds("raw-g") and "Membership" in kinds("raw-g")
    assert not (arch / layout.BUILD_YAML).exists()                     # export still built nothing
    cli.main(["build", str(arch)])
    assert cli.main(["export", str(arch), "--format", "csv", "-o", str(tmp_path / "built-g")]) == 0
    assert "sameAs" in kinds("built-g")
    lite = tmp_path / "lite.hydra"
    cli.main(["pack", str(arch), "-o", str(lite), "--no-parsed"])
    assert cli.main(["export", str(lite), "--format", "csv", "-o", str(tmp_path / "lite-g")]) == 0
    assert "sameAs" not in kinds("lite-g")

def test_hints_set_copies_the_image_writes_one_quoted_rule_and_refuses_mistakes(tmp_path, capsys):
    import yaml
    arch = _built(tmp_path)
    img = tmp_path / "glen.webp"
    img.write_bytes(b"RIFF....WEBPVP8 ")
    hp = arch / layout.HINTS
    assert cli.main(["hints", "set", str(arch), "portrait", str(img), "--schema", "Person",
                     "--name", "Glen (no role, position Chef)", "--no-build"]) == 0
    assert (arch / layout.RESOURCES_DIR / "portraits" / "glen.webp").read_bytes() == img.read_bytes()
    rules = yaml.safe_load(hp.read_text())["hints"]
    assert rules[-1] == {"match": {"schema": "Person", "name": "Glen (no role, position Chef)"},
                         "set": {"portrait": "portraits/glen.webp"}}
    kept = hp.read_text()
    assert kept.startswith("# .hydra/rules/hints.yaml")                     # the comments stay
    with pytest.raises(SystemExit, match="no position 'Kook'"):
        cli.main(["hints", "set", str(arch), "thumb", str(img), "--position", "Kook"])
    assert hp.read_text() == kept                                           # put back as it was
    clash = tmp_path / "x" / "glen.webp"
    clash.parent.mkdir()
    clash.write_bytes(b"something else")
    with pytest.raises(SystemExit, match="already in"):
        cli.main(["hints", "set", str(arch), "portrait", str(clash), "--name", "Glen"])
    with pytest.raises(SystemExit, match="say which entities"):
        cli.main(["hints", "set", str(arch), "portrait", str(img)])
    capsys.readouterr()
    assert cli.main(["hints", "set", str(arch), "thumb", "portraits/glen.webp", "--position", "Leader"]) == 0
    out = capsys.readouterr().out
    assert "reaches" in out
    assert cli.main(["hints", str(arch)]) == 0 and "images on" in capsys.readouterr().out


def test_vanilla_ftm_proof_is_sources_inside_and_proof_again_only_in_an_ftm_export(tmp_path):
    from hydra.cli import check as check_cli
    arch = tmp_path / "ftm"
    cli.main(["init", str(arch)])
    raw = "\n".join(json.dumps(r) for r in [                                 # vanilla FtM JSON lines, as exported
        {"id": "doc-1", "schema": "Document", "properties": {"title": ["Case file"]}},
        {"id": "p1", "schema": "Person", "properties": {"name": ["Ann Lee"], "proof": ["doc-1"]}}])
    f = arch / layout.COLLECTIONS_DIR / "vanilla.json"
    f.write_text(raw, encoding="utf-8")
    assert not [i for i in check_cli.run(arch) if "proof" in json.dumps(i)]   # normal input: nothing to report
    assert cli.main(["build", str(arch)]) == 0
    assert f.read_text(encoding="utf-8") == raw                               # the loaded file is never rewritten
    for out in (arch / layout.PARSED_DIR).iterdir():                          # inside hydra it is `sources` only
        assert '"proof"' not in out.read_text(encoding="utf-8"), out.name
    claims = [json.loads(l) for l in (arch / layout.PARSED_DIR / "claims.jsonl").read_text().splitlines()]
    assert {c["prop"] for c in claims if c["entity"] == "vanilla:p1"} == {"name", "sources"}
    for fmt, field in (("ftm", "proof"), ("hydra-ftm", "sources")):
        out = tmp_path / f"x.{fmt}.jsonl"
        assert cli.main(["export", str(arch), "--format", fmt, "-o", str(out)]) == 0
        ann = next(e for e in map(json.loads, out.read_text().splitlines()) if e["id"] == "vanilla:p1")
        assert field in ann["properties"] and {"proof", "sources"} - {field} - set(ann["properties"]) == {
            "proof", "sources"} - {field}


def test_import_reads_back_every_export_format_to_the_same_graph(tmp_path, capsys):
    import csv
    src = _built(tmp_path)
    def graph(arch, name):
        out = tmp_path / name
        assert cli.main(["export", str(arch), "--format", "csv", "-o", str(out)]) == 0
        nodes = {r["id"]: (r["schema"], r["caption"]) for r in csv.DictReader((out / "nodes.csv").open())}
        edges = {(r["source"], r["target"], r["type"], r["role"], r["start"], r["end"])
                 for r in csv.DictReader((out / "edges.csv").open()) if r["type"] not in ("placedUnder", "sameAs")}
        return nodes, edges
    want = graph(src, "orig")
    for fmt in ("ftm", "hydra-ftm", "csv", "graphml"):
        exported = tmp_path / f"case.{fmt}"
        assert cli.main(["export", str(src), "--format", fmt, "-o", str(exported)]) == 0
        arch = tmp_path / f"in-{fmt}"
        cli.main(["init", str(arch)])
        assert cli.main(["import", str(arch), str(exported), "--format", fmt]) == 0
        assert (arch / layout.COLLECTIONS_DIR / "case.json").is_file()            # named after the file
        if fmt in ("ftm", "hydra-ftm"):                                             # copied as it is
            assert (arch / layout.COLLECTIONS_DIR / "case.json").read_bytes() == exported.read_bytes()
        assert graph(arch, f"back-{fmt}") == want, fmt
    with pytest.raises(SystemExit, match="exists; --force replaces it"):
        cli.main(["import", str(arch), str(exported), "--format", "graphml"])
    assert cli.main(["import", str(arch), str(exported), "--format", "graphml", "--force", "--no-build"]) == 0


def test_a_confirmed_organization_bounds_the_position_rules(tmp_path):
    import yaml
    M = lambda i, member, org, role: {"id": i, "schema": "Membership",
                                      "properties": {"member": [member], "organization": [org], "role": [role]}}
    recs = [{"id": "outer", "schema": "Organization", "properties": {"name": ["Outer Consortium"]}},
            {"id": "inner", "schema": "Organization", "properties": {"name": ["Inner Crew"]}},
            {"id": "boss", "schema": "Person", "properties": {"name": ["Outer Boss"]}},
            {"id": "lead", "schema": "Person", "properties": {"name": ["Inner Lead"]}},
            {"id": "marty", "schema": "Person", "properties": {"name": ["Marty Guard"]}},
            M("m1", "Inner Crew", "Outer Consortium", "member"), M("m2", "Outer Boss", "Outer Consortium", "leader"),
            M("m3", "Inner Lead", "Inner Crew", "leader"), M("m4", "Marty Guard", "Inner Crew", "head of security")]
    arch = tmp_path / "bound"
    cli.main(["init", str(arch), "--prefix", "b"])
    (arch / layout.COLLECTIONS_DIR / "c.json").write_text(json.dumps(recs), encoding="utf-8")
    (arch / layout.POSITIONS).write_text("Head of security: {below: [Leader], titles: [head of security]}\n",
                                         encoding="utf-8")
    def parent(verdicts):
        (arch / layout.VERDICTS).write_text(yaml.safe_dump(verdicts), encoding="utf-8")
        cli.main(["build", str(arch), "--force"])
        nodes = json.loads((arch / layout.READS["declared"]).read_text())["nodes"]
        return nodes["b:marty"]["pid"], nodes["b:marty"]["placement"]["status"]
    assert parent({})[0] == "b:lead"                                       # the rules: under the crew's Leader
    org = {ids.place_key("b:marty", "b:inner"): "confirmed"}
    assert parent(org) == ("b:lead", "proposed")                          # in the crew: still ranked inside it
    no_lead = {**org, ids.place_key("b:marty", "b:lead"): "rejected"}
    assert parent(no_lead) == ("b:inner", "confirmed")                    # never climbs out to the Outer Boss
