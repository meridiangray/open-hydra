"""check: the problems in an archive's files, without building it.

    hydra-ctl check <dir> [--format text|json]

Runs every check that needs only the files and the schema (lint.check): rule
files, hints, direction, param files, verdict values, collections. A build adds
the checks only it can make (orphan verdicts, literal and duplicate ids, rules
matching nothing) to `.hydra/parsed/build.yaml`; when the last build still stands
(nothing it reads has changed), those are listed too, under "from the last
build", and the counts show both. Never builds. Exits 1 when there is an error,
the last build's included while it stands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from hydra import freshness, layout, lint, resources, schema
from hydra.cli import style
from hydra.structure import fold


def run(root) -> list[dict]:
    root = Path(root)
    schema.load(root=root)
    fam = root / layout.DIRECTION
    return lint.sort(lint.check(root, fold.load_direction(fam if fam.is_file() else None)))


def last_build(root, own: list[dict]) -> tuple[list[dict], dict | None, bool]:
    """(the issues only the last build found, its issue counts, whether it still
    stands). No build: ([], None, False). A build that no longer stands lists none."""
    p = Path(root) / layout.BUILD_YAML
    if not p.is_file():
        return [], None, False
    b = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    stands = freshness.up_to_date(root)
    key = lambda i: (i.get("code"), i.get("file"), i.get("where"), i.get("message"))
    mine = {key(i) for i in own}
    extra = [i for i in b.get("issues") or [] if key(i) not in mine] if stands else []
    return lint.sort(extra), b.get("issue_counts") or {}, stands


def _grid(header: list[str], rows: list[list[str]], right=()) -> list[list[str]]:
    w = [max(len(r[i]) for r in [header] + rows) for i in range(len(header))]
    return [[f"{x:>{w[i]}}" if i in right else f"{x:<{w[i]}}" for i, x in enumerate(r)] for r in [header] + rows]


def render(issues: list[dict], extra=(), built: dict | None = None, stands: bool = False) -> str:
    """The issues grouped by code (level, found by this check or the last build,
    how many, file), then each issue (code, where, message), then the counts:
    this check's, and the last build's when there is one."""
    every = [(i, "check") for i in issues] + [(i, "build") for i in extra]
    out = []
    if every:
        groups: dict[tuple, list] = {}
        for i, by in every:
            groups.setdefault((i["code"], i["level"], by, i["file"]), []).append(i)
        order = {lv: n for n, lv in enumerate(lint.LEVELS)}
        keys = sorted(groups, key=lambda k: (order.get(k[1], 9), -len(groups[k]), k[0]))
        g = _grid(["code", "level", "found by", "count", "file"],
                  [[c, lv, by, str(len(groups[(c, lv, by, f)])), f] for c, lv, by, f in keys], right={3})
        out += [style.aside(("  " + "   ".join(g[0])).rstrip())]
        for (c, lv, by, f), row in zip(keys, g[1:]):
            parts = [("  ", ""), (row[0], "accent"), ("   ", ""), (row[1], "note" if lv != "info" else ""),
                     ("   ", ""), (row[2], "aside"), ("   ", ""), (row[3], ""), ("   ", ""), (row[4], "aside")]
            out.append(style.styled(parts).rstrip())
        rows = [[i["code"], i["where"] or "", i["message"]] for k in keys for i in groups[k]]
        g = _grid(["code", "where", "message"], rows)
        out += ["", style.aside(("  " + "   ".join(g[0])).rstrip())]
        out += [style.styled([("  ", ""), (row[0], "accent"), ("   ", ""), (row[1], "aside"), ("   ", ""),
                              (row[2], "")]).rstrip() for row in g[1:]]
        out.append("")
    counts = {lv: sum(1 for i in issues if i["level"] == lv) for lv in lint.LEVELS}
    head = ["", "check"] + (["build" if stands else "old build"] if built is not None else [])
    labels = {"error": "errors", "warning": "warnings", "info": "info"}
    rows = [[labels.get(lv, lv), str(counts[lv])] + ([str(built.get(lv, 0))] if built is not None else [])
            for lv in lint.LEVELS]
    g = _grid(head, rows, right=set(range(1, len(head))))
    out += [style.aside(("  " + "   ".join(g[0])).rstrip())] + [("  " + "   ".join(r)).rstrip() for r in g[1:]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl check",
                                 description="The problems in an archive's files, without building.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(argv)
    root = resources.archive(a.dir, read_only=True)
    issues = run(root)
    extra, built, stands = last_build(root, issues)
    if a.format == "json":
        print(json.dumps(issues + [{**i, "from": "build"} for i in extra], indent=1, ensure_ascii=False))
    else:
        print(render(issues, extra, built, stands), end="")
    return 1 if any(i["level"] == "error" for i in issues + extra) else 0
