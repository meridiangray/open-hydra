"""Snapshots: every command's output on the demo, and the build's files, pinned.

One demo archive is built once (at a fixed time), then each command below runs
on it and its output, with the archive's path written `<tmp>`, is compared with
`tests/snapshots/<name>.txt`. The build's files are pinned by their hashes
(`build-files.txt`). Any change to what a command prints, or to what the build
writes, fails here and shows the lines that moved: a change that was meant is
accepted by writing the snapshots again,

    HYDRA_SNAPSHOTS=update pytest tests/test_snapshots.py

and the diff of `tests/snapshots/` is the record of what changed."""
import hashlib
import os
from pathlib import Path

import pytest

import test_fold as t  # noqa: E402
from hydra import build, cli, layout  # noqa: E402
from hydra.cli import review  # noqa: E402

SNAPS = Path(__file__).resolve().parent / "snapshots"
UPDATE = os.environ.get("HYDRA_SNAPSHOTS") == "update"
NOW = "2026-01-01T00:00:00+00:00"
D = "<archive>"                                   # replaced by the archive's path

COMMANDS = {
    "details": ["details", D], "details.json": ["details", D, "--format", "json"],
    "check": ["check", D], "check.json": ["check", D, "--format", "json"],
    "todo": ["todo", D], "todo-list": ["todo", D, "--list"], "todo.json": ["todo", D, "--format", "json"],
    "collections": ["collections", D], "defaults": ["defaults", D],
    "claims-walter": ["claims", D, "Walter Hartwell White"],
    "claims-walter.json": ["claims", D, "Walter Hartwell White", "--format", "json"],
    "claims-summary": ["claims", "summary", D], "claims-summary.json": ["claims", "summary", D, "--format", "json"],
    "sources": ["sources", D], "sources.json": ["sources", D, "--format", "json"],
    "sources-hank": ["sources", D, "hank"], "sources-person-uncited": ["sources", D, "person", "--uncited"],
    "tree": ["tree", D], "tree-ascii": ["tree", D, "--ascii"], "tree.json": ["tree", D, "--format", "json"],
    "tree-person": ["tree", D, "person"], "tree-gus": ["tree", D, "gus"],
    "tree-albuquerque": ["tree", D, "albuquerque"], "tree-person-albuquerque": ["tree", D, "person", "albuquerque"],
    "tree-membership": ["tree", D, "membership"], "tree-family": ["tree", D, "family"],
    "tree-ownership": ["tree", D, "ownership"],
    "tree-generic": ["tree", D, "--read", "generic"],
    "positions": ["positions", D], "positions-tree": ["positions", D, "--tree"],
    "positions-unplaced": ["positions", D, "--unplaced"], "positions-nodes": ["positions", D, "--nodes"],
    "positions.json": ["positions", D, "--format", "json"], "positions-mermaid": ["positions", D, "--format", "mermaid"], "position-alias": ["position", D, "--tree"],
    "node-find": ["node", "find", D, "heisenberg"], "node-find.json": ["node", "find", D, "heisenberg", "--format", "json"],
}
REVIEWS = ("merges", "references", "placements")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("snap")
    arch = tmp / "demo"
    cli.main(["init", str(arch)])
    for f in sorted(t.DEMO.glob("*.json")):
        (arch / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    summary = build.build_archive(arch, now=NOW)
    return tmp, arch, summary


def _check(name: str, text: str) -> None:
    p = SNAPS / f"{name}.txt"
    if UPDATE:
        SNAPS.mkdir(exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return
    assert p.is_file(), f"no snapshot {p.name}: write them with HYDRA_SNAPSHOTS=update"
    want = p.read_text(encoding="utf-8")
    if text != want:
        import difflib
        diff = "".join(difflib.unified_diff(want.splitlines(True), text.splitlines(True),
                                            f"snapshots/{p.name}", "now", n=1))
        pytest.fail(f"{name} changed:\n{diff[:6000]}", pytrace=False)


def _run(argv, tmp, capsys) -> str:
    capsys.readouterr()
    code = cli.main(argv)
    out = capsys.readouterr()
    return f"exit {code}\n{out.out}" + (f"--- stderr\n{out.err}" if out.err else "")


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_command_output(name, demo, capsys, monkeypatch):
    tmp, arch, _ = demo
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("NO_COLOR", "1")
    argv = [str(arch) if a == D else a for a in COMMANDS[name]]
    _check(name, _run(argv, tmp, capsys).replace(str(tmp), "<tmp>"))


@pytest.mark.parametrize("kind", REVIEWS)
def test_review_session(kind, demo, monkeypatch):
    """Every question of one kind shown and skipped; nothing written."""
    tmp, arch, _ = demo
    monkeypatch.setenv("NO_COLOR", "1")
    out, vfile = [], arch / layout.VERDICTS
    before = vfile.read_bytes() if vfile.is_file() else None
    review.main([str(arch), "--only", kind, "--no-build"], ask=lambda _p: "", say=out.append)
    assert (vfile.read_bytes() if vfile.is_file() else None) == before          # skipped: nothing written
    _check(f"review-{kind}", "\n".join(map(str, out)).replace(str(tmp), "<tmp>") + "\n")


def test_build_line_and_files(demo):
    """The line a build ends with, and a hash of every file the build wrote."""
    tmp, arch, summary = demo
    os.environ["NO_COLOR"] = "1"
    try:
        line = build.report(arch, summary)
    finally:
        del os.environ["NO_COLOR"]
    parsed = arch / layout.PARSED_DIR
    rows = [f"{hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  {p.name}"
            for p in sorted(parsed.iterdir()) if p.is_file()]
    _check("build-files", line + "\n" + "\n".join(rows) + "\n")


def test_export_and_pack(demo, capsys, monkeypatch):
    tmp, arch, _ = demo
    monkeypatch.setenv("NO_COLOR", "1")
    out = []
    (tmp / "out").mkdir(exist_ok=True)
    for fmt, dest in (("ftm", "e.jsonl"), ("csv", "csv"), ("graphml", "g.graphml")):
        out.append(_run(["export", str(arch), "--format", fmt, "-o", str(tmp / "out" / dest)], tmp, capsys))
    files = sorted(p for p in (tmp / "out").rglob("*") if p.is_file())
    out += [f"{hashlib.sha256(p.read_bytes()).hexdigest()[:16]}  {p.relative_to(tmp).as_posix()}"
            for p in files if p.name != "export.yaml"]
    out.append(_run(["pack", str(arch), "-o", str(tmp / "out" / "demo.hydra")], tmp, capsys))
    _check("export-pack", "\n".join(out).replace(str(tmp), "<tmp>") + "\n")
