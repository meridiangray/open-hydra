"""build.py: an archive directory in, parsed/* out — on the real demo corpus."""
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml


import test_fold as t  # noqa: E402
from hydra import build, layout  # noqa: E402
from hydra.ingest import source_of  # noqa: E402
from hydra.review import verdicts as vd  # noqa: E402
from _template import copy_template  # noqa: E402
from _paths import SRC as SRC_DIR  # noqa: E402

NOW = "2026-01-01T00:00:00+00:00"


def _archive(dest: Path) -> Path:
    copy_template(dest)
    for f in t.DEMO.glob("*.json"):
        shutil.copy(f, dest / layout.COLLECTIONS_DIR / f.name)
    return dest


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = _archive(tmp_path_factory.mktemp("arch") / "arch")
    return root, build.build_archive(root, now=NOW)


def _jl(root, rel):
    return [json.loads(l) for l in (root / rel).read_text(encoding="utf-8").splitlines() if l.strip()]


def test_every_output_is_written_and_counts_match_the_demo(built):
    root, s = built
    for rel in (layout.PARSED_YAML, layout.BUILD_YAML, layout.CLAIMS_JSONL, layout.IDENTICAL_JSONL,
                layout.LEDGER_JSONL, build.READS["generic"], build.READS["declared"]):
        assert (root / rel).is_file(), rel
    assert s["reads"]["declared"]["nodes"] == 79 and s["reads"]["declared"]["roots"] == 19
    assert s["ledger"]["merges"] == {"auto": 17, "proposed": 14}
    assert yaml.safe_load((root / layout.BUILD_YAML).read_text(encoding="utf-8"))["records"] == s["records"]
    assert [i for i in s["issues"] if i["level"] != "info"] == []


def test_title_coverage_counts_matched_titles_per_source(built):
    _, s = built
    for read, cov in s["title_coverage"].items():
        assert set(cov) == {"role", "position", "Position.name"}
        for c in cov.values():
            assert c["matched"] + len(c["unmatched"]) == c["titles"]
    # the template's positions.yaml is empty, so both reads cover the same titles
    assert s["title_coverage"]["declared"] == s["title_coverage"]["generic"]


def test_ids_are_tagged_and_the_tags_are_stored_in_the_manifest(built):
    root, s = built
    ir = json.loads((root / build.READS["declared"]).read_text(encoding="utf-8"))
    assert all(source_of(i) for i in ir["nodes"])
    walt = next(n for n in ir["nodes"].values() if n["caption"] == "Walter Hartwell White")
    assert walt["id"] == "heisenberg:p-walt" and walt["position"] == "Leader"
    assert ir["nodes"][walt["pid"]]["caption"] == "Heisenberg Organization"
    man = json.loads((root / layout.COLLECTIONS_MANIFEST).read_text(encoding="utf-8"))
    assert {k: v["prefix"] for k, v in man["collections"].items()} == s["prefixes"]
    assert all(source_of(c["entity"]) for c in _jl(root, layout.CLAIMS_JSONL))


def test_identical_and_ledger_files_split_the_rows_and_the_reads_have_no_ledger(built):
    root, _ = built
    assert {r["rel"] for r in _jl(root, layout.IDENTICAL_JSONL)} == {"sameAs"}
    assert "sameAs" not in {r["rel"] for r in _jl(root, layout.LEDGER_JSONL)}
    for which in ("generic", "declared"):
        ir = json.loads((root / build.READS[which]).read_text(encoding="utf-8"))
        assert "ledger" not in ir and "claims" not in ir and ir["read"] == which
    assert "diff" in json.loads((root / build.READS["declared"]).read_text(encoding="utf-8"))


def test_a_second_build_is_identical(tmp_path):
    root = _archive(tmp_path / "a")
    build.build_archive(root, now=NOW)
    first = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / ".hydra" / "parsed").iterdir()}
    man = (root / layout.COLLECTIONS_MANIFEST).read_bytes()
    build.build_archive(root, now=NOW)
    assert {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / ".hydra" / "parsed").iterdir()} == first
    assert (root / layout.COLLECTIONS_MANIFEST).read_bytes() == man


def test_a_manifest_tag_chosen_by_the_user_is_used(tmp_path):
    root = _archive(tmp_path / "a")
    mp = root / layout.COLLECTIONS_MANIFEST
    man = json.loads(mp.read_text(encoding="utf-8"))
    man["collections"]["heisenberg"]["prefix"] = "abq"
    mp.write_text(json.dumps(man), encoding="utf-8")
    s = build.build_archive(root, now=NOW)
    assert s["prefixes"]["heisenberg"] == "abq"
    ir = json.loads((root / build.READS["declared"]).read_text(encoding="utf-8"))
    assert any(i == "abq:p-walt" for i in ir["nodes"])


def test_no_tag_keeps_source_ids(tmp_path):
    root = _archive(tmp_path / "a")
    s = build.build_archive(root, prefix=False, now=NOW)
    ir = json.loads((root / build.READS["declared"]).read_text(encoding="utf-8"))
    assert "p-walt" in ir["nodes"] and "prefixes" not in s
    man = json.loads((root / layout.COLLECTIONS_MANIFEST).read_text(encoding="utf-8"))
    assert not any("prefix" in v for v in man["collections"].values())


def test_write_false_touches_nothing(tmp_path):
    root = _archive(tmp_path / "a")
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    s = build.build_archive(root, write=False, now=NOW)
    assert s["reads"]["declared"]["nodes"] == 79
    assert {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_verdicts_are_read_from_the_archive_and_applied(tmp_path):
    root = _archive(tmp_path / "a")
    build.build_archive(root, now=NOW)
    merge = next(r for r in _jl(root, layout.IDENTICAL_JSONL) if r["status"] == "proposed")
    ref = next(r for r in _jl(root, layout.LEDGER_JSONL) if r["rel"] == "references" and r["candidates"])
    cand = ref["candidates"][0]["id"]
    vf = root / layout.VERDICTS
    vf.write_text(yaml.safe_dump({merge["id"]: {"status": "confirmed", "basis": merge["basis"]},
                                  ref["id"]: cand}), encoding="utf-8")
    build.build_archive(root, now=NOW)
    m2 = next(r for r in _jl(root, layout.IDENTICAL_JSONL) if r["id"] == merge["id"])
    r2 = next(r for r in _jl(root, layout.LEDGER_JSONL) if r["id"] == ref["id"])
    assert m2["status"] == "confirmed"
    assert r2["status"] == "pinned" and r2["choice"] == cand


def test_disagreeing_verdict_files_resolve_to_rejected_and_pins_cancel(tmp_path):
    d = tmp_path / "r" / ".hydra" / "review"
    (d / "src").mkdir(parents=True)
    (d / "verdicts.yaml").write_text(yaml.safe_dump({"merge-1": "confirmed", "ref-1": "a", "cap-1": "x"}))
    (d / "src" / "verdicts.yaml").write_text(yaml.safe_dump({"merge-1": "rejected", "ref-1": "b", "bogus": "maybe"}))
    got, issues = vd.load(tmp_path / "r")
    assert got == {"merge-1": "rejected", "cap-1": "x"} and len(issues) == 2


def test_a_decided_row_whose_evidence_vanished_is_kept_as_stale():
    prev = [{"id": "merge-x", "rel": "sameAs", "status": "proposed", "a": "p", "b": "q"},
            {"id": "ref-y", "rel": "references", "status": "proposed"}]
    out = build.merge_ledgers([], [], prev, {"merge-x": "confirmed", "ref-y": "c"})
    assert [(e["id"], e["status"], e.get("stale")) for e in out] == [("merge-x", "confirmed", True)]


def test_an_archive_with_no_collections_is_an_error(tmp_path):
    root = tmp_path / "a"
    copy_template(root)
    with pytest.raises(ValueError):
        build.build_archive(root, now=NOW)


def test_a_link_written_as_a_record_id_is_followed(tmp_path):
    root = tmp_path / "lit"
    copy_template(root)
    (root / layout.COLLECTIONS_DIR / "c.json").write_text(json.dumps([
        {"id": "p1", "schema": "Person", "properties": {"name": ["Ann Lee"]}},
        {"id": "o1", "schema": "Organization", "properties": {"name": ["Acme Widgets"]}},
        {"id": "m1", "schema": "Membership", "properties": {"member": ["p1"], "organization": ["Acme Widgets"]}},
        {"id": "d1", "schema": "Document", "properties": {"title": ["Report"]}},
        {"id": "g1", "schema": "Documentation", "properties": {"document": ["d1"], "entity": ["Ann Lee"]}},
    ]), encoding="utf-8")
    s = build.build_archive(root, now=NOW)
    assert not [i for i in s["issues"] if i["code"] == "records.literal-id"]
    nodes = json.loads((root / build.READS["generic"]).read_text(encoding="utf-8"))["nodes"]
    assert any(r["record"] == "c:m1" for r in nodes["c:p1"]["rels"])           # member: p1, followed by its id
    assert any(x["id"] == "c:d1" for x in nodes["c:p1"]["linked"])              # and the document pointer


def test_a_placement_verdict_in_basis_form_is_read_like_a_plain_one(tmp_path):
    root = _archive(tmp_path / "pv")
    build.build_archive(root, now=NOW)
    rows = _jl(root, layout.LEDGER_JSONL)
    key = next(r["id"] for r in rows if r["rel"] == "placedUnder" and r["status"] == "proposed")
    vfile = root / layout.VERDICTS
    vfile.write_text(yaml.safe_dump({key: {"status": "rejected", "basis": "x"}}), encoding="utf-8")
    s = build.build_archive(root, now=NOW)
    vfile.write_text(yaml.safe_dump({key: "rejected"}), encoding="utf-8")
    assert build.build_archive(root, now=NOW)["ledger"] == s["ledger"]


def test_builds_are_identical_across_hash_seeds(tmp_path):
    import os
    import subprocess
    code = ("import sys; sys.path.insert(0, %r); from hydra import build; "
            "build.build_archive(sys.argv[1], now=%r)" % (str(SRC_DIR), NOW))
    outs = []
    for seed in ("1", "2"):
        root = _archive(tmp_path / f"s{seed}")
        subprocess.run([sys.executable, "-c", code, str(root)], check=True,
                       env={**os.environ, "PYTHONHASHSEED": seed})
        outs.append({p.name: p.read_bytes() for p in sorted((root / layout.PARSED_DIR).iterdir())})
    assert outs[0] == outs[1]


def test_builds_are_identical_when_records_are_shuffled(tmp_path):
    """Record order within a file is not data: shuffling it changes no byte of
    parsed/*, parallel edges and report lists included."""
    import random
    outs = []
    for seed in (None, 7):
        root = _archive(tmp_path / f"r{seed}" / "arch")
        if seed is not None:
            rng = random.Random(seed)
            for f in (root / layout.COLLECTIONS_DIR).glob("*.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    rng.shuffle(data)
                    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        build.build_archive(root, now=NOW)
        outs.append({p.name: p.read_bytes() for p in sorted((root / layout.PARSED_DIR).iterdir())})
    assert outs[0] == outs[1]


def test_subject_is_read_from_hydra_yaml_and_flagged_in_hierarchy_yaml(tmp_path):
    root = _archive(tmp_path / "subj")
    (root / layout.MANIFEST).write_text(
        (root / layout.MANIFEST).read_text(encoding="utf-8")
        + "subject: {label: Acme, type: Organization}\n", encoding="utf-8")
    (root / layout.POSITIONS).write_text("subject: {label: Old, type: Organization}\n", encoding="utf-8")
    s = build.build_archive(root, write=False, now=NOW)
    assert s["subject"] == {"label": "Acme", "type": "Organization"}
    assert any(i["code"] == "rules.subject-misplaced" for i in s["issues"])


def test_duplicate_ids_keep_the_first_record_and_are_reported(tmp_path):
    root = copy_template(tmp_path / "dup")
    recs = [{"id": "p1", "schema": "Person", "properties": {"name": ["Ann Lee"]}},
            {"id": "p1", "schema": "Person", "properties": {"name": ["Bob Ray"]}}]
    (root / layout.COLLECTIONS_DIR / "a.json").write_text(json.dumps(recs), encoding="utf-8")
    (root / layout.COLLECTIONS_DIR / "b.json").write_text(json.dumps(recs[:1]), encoding="utf-8")
    s = build.build_archive(root, prefix=False, write=False, now=NOW)
    dup = lambda s: [(i["where"], i["file"]) for i in s["issues"] if i["code"] == "records.duplicate-id"]
    assert dup(s) == [("p1", "collections/a"), ("p1", "collections/b")]
    prefixed = build.build_archive(root, write=False, now=NOW)
    assert dup(prefixed) == [("a:p1", "collections/a")]


def test_a_typo_in_a_position_file_is_reported(tmp_path):
    root = _archive(tmp_path / "typo")
    (root / layout.POSITIONS).write_text("Boss: {bellow: [Leader], rank: 3}\n", encoding="utf-8")
    issues = build.build_archive(root, write=False, now=NOW)["issues"]
    shape = [(i["file"], i["where"]) for i in issues if i["code"] == "positions.shape"]
    assert (layout.POSITIONS, "Boss.bellow") in shape and (layout.POSITIONS, "Boss.rank") in shape


def test_a_large_archive_gets_a_size_warning(tmp_path, monkeypatch):
    root = _archive(tmp_path / "big")
    size = lambda: [i for i in build.build_archive(root, write=False, now=NOW)["issues"]
                    if i["code"] == "archive.size"]
    assert size() == []
    monkeypatch.setattr(build, "RECORD_GUIDE", 10)
    assert size() and size()[0]["level"] == "warning"


def test_every_record_placement_names_edge_records_found_in_claims(built):
    """A node's placement, and its `placedUnder` row, list the records it rests on,
    and each is an entity of claims.jsonl: the tree traces back to its sources.
    Only a rule placement (titles, no record) lists none."""
    root, _ = built
    claimed = {c["entity"] for c in _jl(root, layout.CLAIMS_JSONL)}
    nodes = json.loads((root / ".hydra" / "parsed" / "declared.json").read_text(encoding="utf-8"))["nodes"]
    placed = [n["placement"] for n in nodes.values() if n.get("placement")]
    assert placed
    for p in placed:
        if p["criteria"].startswith("rules:"):
            assert p["records"] == []
        else:
            assert p["records"] and set(p["records"]) <= claimed, p
    rows = [e for e in _jl(root, layout.LEDGER_JSONL) if e["rel"] == "placedUnder"]
    assert all("records" in e for e in rows)


def test_the_parse_cache_skips_unchanged_yaml_and_sees_an_edit(tmp_path):
    import os
    import subprocess
    from hydra import schema, yamlcache
    root = _archive(tmp_path / "c")
    build.build_archive(root, now=NOW)
    yamlcache.save()
    assert (root / yamlcache.CACHE_DIR / "yaml.json").is_file()
    scope = {p.relative_to(root).as_posix() for p in root.rglob("*")
             if p.is_file() and schema.in_config_scope(p.relative_to(root).as_posix())}
    assert set(schema.config_files(root)) == scope                      # the walk finds the whole config plane
    count = ("import sys; sys.path.insert(0, %r); from hydra import build, yamlcache; n = [0]; "
             "real = yamlcache.parse; yamlcache.parse = lambda t: (n.__setitem__(0, n[0] + 1), real(t))[1]; "
             "build.build_archive(sys.argv[1], now=%r); print(n[0])" % (str(SRC_DIR), NOW))
    run = lambda: int(subprocess.run([sys.executable, "-c", count, str(root)], check=True, capture_output=True,
                                     text=True).stdout.split()[-1])
    assert run() == 0                                                   # a fresh process parses nothing
    person = root / layout.PARAMS_DIR / "Person.param.yaml"
    person.write_text(person.read_text(encoding="utf-8").replace("  - weakAlias\n", ""), encoding="utf-8")
    assert run() == 1                                                   # ...but the edited file, once
    assert "weakAlias" not in yamlcache.load(person)["match"]


def test_build_skips_when_nothing_changed_and_rebuilds_on_any_change(tmp_path, capsys):
    from hydra import yamlcache
    root = _archive(tmp_path / "s")
    calls = []
    real = build.build_archive
    build.build_archive = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        run = lambda *flags: (build.main([str(root), *flags]), capsys.readouterr().out)[1]
        first = run()
        assert len(calls) == 1
        assert run() == first and len(calls) == 1                     # unchanged: same output, no build
        assert run("--force") == first and len(calls) == 2            # --force always builds
        (root / layout.HINTS).write_text((root / layout.HINTS).read_text(encoding="utf-8") + "\n", encoding="utf-8")
        run()
        assert len(calls) == 3                                        # a rule file changed
        (root / layout.PARSED_DIR / "generic.json").unlink()
        run()
        assert len(calls) == 4 and (root / layout.PARSED_DIR / "generic.json").is_file()   # an output went missing
    finally:
        build.build_archive = real


def test_source_entries_are_cited_by_id_and_are_not_tree_nodes(tmp_path):
    root = tmp_path / "src"
    copy_template(root)
    (root / layout.SOURCE_ENTRIES).mkdir(parents=True, exist_ok=True)
    (root / layout.SOURCE_ENTRIES / "wikipedia.json").write_text("\n".join(json.dumps(r) for r in [
        {"id": "wp-gus", "schema": "Article", "properties": {"title": ["Gus Fring"], "publisher": ["Wikipedia"],
                                                             "sourceUrl": ["https://en.wikipedia.org/wiki/Gus_Fring"]}},
        {"id": "wp-oops", "schema": "Person", "properties": {"name": ["Not A Source"]}}]), encoding="utf-8")
    (root / layout.COLLECTIONS_DIR / "c.json").write_text(json.dumps(
        {"id": "p1", "schema": "Person", "properties": {"name": ["Gustavo Fring"], "sources": ["wp-gus"]}}), encoding="utf-8")
    s = build.build_archive(root, now=NOW)
    nodes = json.loads((root / build.READS["generic"]).read_text(encoding="utf-8"))["nodes"]
    gus = next(n for n in nodes.values() if n["caption"] == "Gustavo Fring")
    assert [x["caption"] for x in gus["linked"]] == ["Gus Fring"]              # cited by id, shown as evidence
    assert not any(n.get("schema") == "Article" for n in nodes.values())       # a source is not a tree node
    assert not s["ledger"].get("references")                                    # nothing left unresolved
    assert [i["where"] for i in s["issues"] if i["code"] == "sources.not-a-document"] == ["sources-wikipedia:wp-oops"]
    assert not [i for i in s["issues"] if i["code"] == "records.unknown-property"]   # `sources` is a known field
    from hydra.cli import export
    for fmt, field in (("ftm", "proof"), ("hydra-ftm", "sources")):        # FtM's own name out, ours kept
        out = tmp_path / f"x.{fmt}.jsonl"
        export.main([str(root), "--format", fmt, "-o", str(out)])
        ent = next(e for e in map(json.loads, out.read_text(encoding="utf-8").splitlines()) if e["id"] == "c:p1")
        assert ent["properties"][field] == ["sources-wikipedia:wp-gus"]       # a document is addressed by id
