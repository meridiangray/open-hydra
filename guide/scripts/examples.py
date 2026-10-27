"""Write the command examples the docs show: every example run on the demo, as raw text.

The demo archive (examples/demo/collections) is built once at a fixed time, and
each example runs on its own fresh copy, so what one example changes never reaches
the next. The clock is pinned, colour is off and the terminal is 120 columns wide,
so the same code always prints the same files. Each one is written to
docs/examples/<name>.txt as a terminal would show it: the command after `$ `,
then what it printed.

    python guide/scripts/examples.py           # write docs/examples/
    python guide/scripts/examples.py --check   # exit 1 if any example changed

Run it with hydra's dependencies installed (PyYAML, pydantic). It imports hydra from
the repository this file sits in.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1]
HYDRA_GIT = GUIDE.parent
DEMO = HYDRA_GIT / "examples" / "demo" / "collections"
OUT = GUIDE / "docs" / "examples"
PAGE = GUIDE / "docs" / "commands" / "output.md"
sys.path.insert(0, str(HYDRA_GIT / "src"))

from hydra import build, cli, layout  # noqa: E402
from hydra.cli import review  # noqa: E402

NAME = "breakingbad"                  # the archive's folder, as the examples show it
SHOWN = "~/cases"                     # what the folder above it is shown as
FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED if tz else FIXED.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FIXED.replace(tzinfo=None)


def _pin_clock() -> None:
    """Every rebuild and backup a command makes is stamped 2026-01-01. The commands
    are imported first, since hydra loads each one only when it runs."""
    import importlib
    import pkgutil
    import hydra.cli as pkg
    for m in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"hydra.cli.{m.name}")
    for name, mod in list(sys.modules.items()):
        if name.startswith("hydra") and getattr(mod, "datetime", None) is datetime:
            mod.datetime = _Clock


# ---- running a command --------------------------------------------------------


def _capture(fn) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            fn()
        except SystemExit as e:                      # argparse and hydra's own errors
            if e.code not in (None, 0) and not isinstance(e.code, int):
                print(e.code)
    return out.getvalue()


def _quote(a: str) -> str:
    return f'"{a}"' if re.search(r"[\s|]", a) else a


def run(argv: list[str]) -> str:
    return f"$ hydra-ctl {' '.join(map(_quote, argv))}\n" + _capture(lambda: cli.main(argv))


def run_review(argv: list[str], answers: list[str]) -> str:
    """A review session, answering from `answers` and quitting when they run out."""
    said, left = [], list(answers)

    def ask(prompt):
        got = left.pop(0) if left else "q"
        said.append(f"{prompt}{got}")
        return got

    def go():
        review.main(argv[1:], ask=ask, say=lambda *a: said.append(" ".join(map(str, a))))

    printed = _capture(go)
    return f"$ hydra-ctl {' '.join(map(_quote, argv))}\n" + printed + "\n".join(said) + "\n"


def data(argv: list[str]) -> dict:
    return json.loads(_capture(lambda: cli.main(argv + ["--format", "json"])))


# ---- the examples -------------------------------------------------------------
# Each: name, the command it documents, and a function given the archive's
# folder (the working directory) that returns the transcript.


def _ids(kind: str, on: str = "") -> list[str]:
    """The open questions of one kind, optionally only those about a collection's records."""
    rows = data(["todo"]).get(kind) or []
    return [q["id"] for q in rows if not on or on in json.dumps(q.get("row") or {})]


GRAY_MATTER = [
    {"id": "mem-graymatter", "schema": "Membership",
     "properties": {"member": ["Gretchen Schwartz"], "organization": ["Gray Matter Technologies"],
                    "role": ["co-founder"]}},
    {"id": "emp-graymatter", "schema": "Employment",
     "properties": {"employee": ["Walter Hartwell White"], "employer": ["Gray Matter Technologies"],
                    "role": ["co-founder"]}},
]


def with_stubs(make):
    """The demo has no stubs: add links to two names no record has, and rebuild first."""
    def go(ws: Path) -> str:
        (ws / layout.COLLECTIONS_DIR / "graymatter.json").write_text(json.dumps(GRAY_MATTER, indent=1) + "\n")
        _capture(lambda: cli.main(["build"]))
        return make(ws)
    return go


def _icon(ws: Path) -> str:
    p = ws.parent / "pics" / "flask.svg"
    p.parent.mkdir(exist_ok=True)
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M6 1h4v5l4 8H2l4-8z"/></svg>\n')
    return "../pics/flask.svg"


def _export(fmt: str, dest: str):
    def go(ws: Path) -> str:
        return run(["export", "--format", fmt, "-o", dest])
    return go


def _import(fmt: str, src: str, *extra: str):
    def go(ws: Path) -> str:
        _capture(lambda: cli.main(["export", "--format", fmt, "-o", f"../{src}"]))
        for f in (ws / layout.COLLECTIONS_DIR).glob("*.json"):
            if f.name != "manifest.json":
                f.unlink()
        return run(["import", f"../{src}", "--format", fmt, *extra])
    return go


def cmds(*argvs: list[str]):
    return lambda ws: "\n".join(run(a) for a in argvs)


EXAMPLES: dict[str, tuple[str, object]] = {
    # setup
    "init": ("init", lambda ws: run(["init", "../htest", "--name", "Breaking Bad", "--prefix", "bb"])),
    "init-pack": ("init", lambda ws: (_capture(lambda: cli.main(["pack", "-o", "../case-one.hydra"])),
                                      run(["init", "../case-one.hydra"]))[1]),
    "activate": ("activate", lambda ws: (os.chdir(ws.parent), cmds(["activate", NAME], ["activate"], ["deactivate"])(ws))[1]),
    "import-ftm": ("import", _import("ftm", "opensanctions.ftm.jsonl")),
    "import-hydra-ftm": ("import", _import("hydra-ftm", "case.hydra-ftm.jsonl", "--name", "fring")),
    "import-csv": ("import", _import("csv", "case-graph")),
    "import-graphml": ("import", _import("graphml", "case.graphml")),
    "build": ("build", cmds(["build"])),
    "build-force": ("build", cmds(["build", "--force"])),
    "build-verbose": ("build", cmds(["build", "--force", "--verbose"])),
    # explore
    "check": ("check", cmds(["check"])),
    "check-json": ("check", cmds(["check", "--format", "json"])),
    "details": ("details", cmds(["details"])),
    "details-json": ("details", cmds(["details", "--format", "json"])),
    "tree": ("tree", cmds(["tree"])),
    "tree-person": ("tree", cmds(["tree", "person"])),
    "tree-gus": ("tree", cmds(["tree", "gus"])),
    "tree-gus-mermaid": ("tree", cmds(["tree", "gus", "--format", "mermaid"])),
    "tree-gus-mermaid-vertical": ("tree", cmds(["tree", "gus", "--format", "mermaid", "--vertical"])),
    "tree-gus-mermaid-lateral": ("tree", cmds(["tree", "gus", "--format", "mermaid", "--lateral"])),
    "tree-gus-mermaid-lr": ("tree", cmds(["tree", "gus", "--format", "mermaid", "--direction", "LR"])),
    "tree-gus-mermaid-singletons": ("tree", cmds(["tree", "gus", "--format", "mermaid", "--lateral",
                                                  "--singletons"])),
    "tree-family": ("tree", cmds(["tree", "family"])),
    "tree-family-employment": ("tree", cmds(["tree", "family", "employment"])),
    "tree-organization-sources": ("tree", cmds(["tree", "organization", "sources"])),
    "tree-stubs": ("tree", with_stubs(cmds(["tree", "employment", "membership", "--stubs"]))),
    "tree-generic": ("tree", cmds(["tree", "--read", "generic"])),
    "tree-ascii": ("tree", cmds(["tree", "gus", "--ascii"])),
    "tree-json": ("tree", cmds(["tree", "gus", "--format", "json"])),
    "tree-mermaid": ("tree", cmds(["tree", "--format", "mermaid"])),
    "tree-mermaid-vertical": ("tree", cmds(["tree", "--format", "mermaid", "--vertical", "--direction", "LR"])),
    "tree-mermaid-family": ("tree", cmds(["tree", "family", "--format", "mermaid"])),
    "positions": ("positions", cmds(["positions"])),
    "positions-tree-nodes": ("positions", cmds(["positions", "--tree", "--nodes"])),
    "positions-unplaced": ("positions", cmds(["positions", "--unplaced"])),
    "positions-unplaced-json": ("positions", cmds(["positions", "--unplaced", "--format", "json"])),
    "positions-mermaid": ("positions", cmds(["positions", "--format", "mermaid"])),
    "claims": ("claims", cmds(["claims"])),
    "claims-gus": ("claims", cmds(["claims", "gus"])),
    "claims-person-walt": ("claims", cmds(["claims", "person", "walt"])),
    "claims-prop": ("claims", cmds(["claims", "Gustavo Fring", "--prop", "weakAlias"])),
    "claims-gus-sources-json": ("claims", cmds(["claims", "gus", "sources", "--format", "json"])),
    "claims-summary": ("claims", cmds(["claims", "summary"])),
    "node-find": ("node find", cmds(["node", "find", "walt"])),
    "node-find-person": ("node find", cmds(["node", "find", "person", "heisenberg"])),
    "node-find-id": ("node find", cmds(["node", "find", "p-walt", "--field", "id"])),
    "sources": ("sources", cmds(["sources"])),
    "sources-hank": ("sources", cmds(["sources", "hank"])),
    "sources-person-uncited": ("sources", cmds(["sources", "person", "--uncited"])),
    "sources-casefile": ("sources", cmds(["sources", "casefile"])),
    "sources-json": ("sources", cmds(["sources", "--format", "json"])),
    # decide
    "todo": ("todo", cmds(["todo"])),
    "todo-list": ("todo", cmds(["todo", "--list"])),
    "todo-list-placements": ("todo", cmds(["todo", "--list", "placements"])),
    "todo-json": ("todo", cmds(["todo", "--format", "json"])),
    "review-merges": ("review", lambda ws: run_review(["review", "--only", "merges"], ["2"])),   # two different events: keep them apart
    "review-references": ("review", lambda ws: run_review(["review", "--only", "references"], ["2"])),
    "review-placements": ("review", lambda ws: run_review(["review", "--only", "placements"], ["2", "a"])),
    "answer-merge": ("answer", lambda ws: run(["answer", _ids("merges")[0], "confirm"])),
    "answer-placement": ("answer", lambda ws: cmds(["answer", _ids("placements")[0], "reject"],
                                                    ["answer", _ids("placements")[0], "clear"])(ws)),
    "answer-reference": ("answer", lambda ws: run(["answer", _ids("references")[0], "2"])),
    "reset": ("reset", lambda ws: (_capture(lambda: cli.main(["answer", _ids("merges")[0], "confirm"])),
                                   run(["reset", "--yes"]))[1]),
    "reset-only": ("reset", lambda ws: (_capture(lambda: cli.main(["answer", _ids("placements")[0], "reject"])),
                                        run(["reset", "--only", "placements", "--yes"]))[1]),
    "stubs": ("stubs", with_stubs(cmds(["stubs"]))),
    "stubs-graduate": ("stubs", with_stubs(cmds(["stubs", "graduate", "Gretchen Schwartz"],
                                                ["stubs", "drop", "Gretchen Schwartz"]))),
    "stubs-graduate-as": ("stubs", with_stubs(cmds(["stubs", "graduate", "Gray Matter Technologies",
                                                    "--as", "Company"]))),
    # share
    "pack": ("pack", cmds(["pack", "-o", "../breakingbad.hydra"])),
    "pack-no-parsed": ("pack", cmds(["pack", "-o", "../case-one.hydra", "--no-parsed"])),
    "unpack": ("unpack", lambda ws: (_capture(lambda: cli.main(["pack", "-o", "../case-one.hydra"])),
                                     run(["unpack", "../case-one.hydra"]))[1]),
    "export-ftm": ("export", _export("ftm", "../breakingbad.ftm.jsonl")),
    "export-hydra-ftm": ("export", _export("hydra-ftm", "../breakingbad.hydra-ftm.jsonl")),
    "export-csv": ("export", _export("csv", "../graph")),
    "export-graphml": ("export", _export("graphml", "../breakingbad.graphml")),
    # settings
    "collections": ("collections", cmds(["collections"])),
    "collections-prefix": ("collections", cmds(["collections", "prefix", "dea", "agency"])),
    "collections-prefix-rekey": ("collections", lambda ws: (
        _capture(lambda: cli.main(["answer", _ids("merges", on='"dea:')[0], "confirm"])),
        cmds(["collections", "prefix", "dea", "agency"], ["collections", "prefix", "dea", "agency", "--rekey"])(ws))[1]),
    "defaults": ("defaults", cmds(["defaults"])),
    "defaults-off-on": ("defaults", cmds(["defaults", "off", "generic"], ["defaults"], ["defaults", "on"])),
    "defaults-restore": ("defaults", cmds(["defaults", "restore", "hints", "params", "--yes"])),
    "defaults-restore-all": ("defaults", cmds(["defaults", "restore", "--all", "--yes"])),
    "hints": ("hints", cmds(["hints"])),
    "hints-set-position": ("hints", cmds(["hints", "set", "thumb", "icons/crown.svg", "--position", "Second-in-command"])),
    "hints-set-titled": ("hints", lambda ws: run(["hints", "set", "thumb", _icon(ws), "--titled", "cook|chemist"])),
}


# ---- writing them -------------------------------------------------------------


def _clean(text: str, ws: Path) -> str:
    """Paths as a person's would read (~/cases/breakingbad/...), no trailing blanks."""
    for p in {str(ws.parent), str(ws.parent.resolve()), ws.parent.as_posix()}:
        text = text.replace(p.replace("\\", "\\\\"), SHOWN).replace(p, SHOWN)   # JSON escapes the backslashes
    text = re.sub(r"~/cases[^\s'\"]*", lambda m: m[0].replace("\\", "/"), text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def generate(dest: Path) -> dict[str, str]:
    os.environ.update({"COLUMNS": "120", "NO_COLOR": "1"})
    os.environ.pop("HYDRA_ARCHIVE", None)
    _pin_clock()
    dest.mkdir(parents=True, exist_ok=True)
    written, home = {}, os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base" / NAME
        _capture(lambda: cli.main(["init", str(base)]))
        for f in sorted(DEMO.glob("*.json")):
            if f.name != "manifest.json":
                (base / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
        build.build_archive(base, now=FIXED.isoformat())
        for i, (name, (_, make)) in enumerate(EXAMPLES.items()):
            ws = Path(tmp) / f"run{i}" / NAME
            shutil.copytree(base, ws)
            os.chdir(ws)
            try:
                text = _clean(make(ws), ws)
            finally:
                os.chdir(home)
            (dest / f"{name}.txt").write_text(text, encoding="utf-8", newline="\n")
            written[name] = text
    return written


def page() -> str:
    """docs/commands/output.md: every example, grouped by command, in the reference's order."""
    order = ["init", "activate", "import", "build", "check", "details", "tree", "positions", "claims",
             "node find", "sources", "todo", "review", "answer", "reset", "stubs", "pack", "unpack", "export",
             "collections", "defaults", "hints"]
    out = ["# Example output", "",
           "What each command prints, run on the Breaking Bad demo archive. Every example is also a raw text file "
           "in `docs/examples/`, linked above its output, and all of them are generated by `guide/scripts/examples.py`.", "",
           "<!-- generated by guide/scripts/examples.py: edit the script, not this page -->", ""]
    for command in order:
        names = [n for n, (c, _) in EXAMPLES.items() if c == command]
        out += [f"## {command}", ""]
        for n in names:
            first = (OUT / f"{n}.txt").read_text(encoding="utf-8").splitlines()[0].removeprefix("$ ")
            first = first.replace('"', "'")             # the title is itself in double quotes
            out += [f'??? example "`{first}`"', "", f"    [{n}.txt](../examples/{n}.txt)", "",
                    "    ```text", f'    --8<-- "{n}.txt"', "    ```", ""]
    return "\n".join(out)


def main() -> int:
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            new = generate(Path(tmp))
        changed = [n for n, t in new.items()
                   if not (OUT / f"{n}.txt").is_file() or (OUT / f"{n}.txt").read_text(encoding="utf-8") != t]
        for n in changed:
            print(f"changed: examples/{n}.txt")
        return 1 if changed else 0
    if OUT.is_dir():
        for f in OUT.glob("*.txt"):
            f.unlink()
    generate(OUT)
    PAGE.write_text(page(), encoding="utf-8", newline="\n")
    print(f"wrote {len(EXAMPLES)} examples to {OUT.relative_to(GUIDE)} and {PAGE.relative_to(GUIDE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
