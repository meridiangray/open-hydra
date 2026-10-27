"""todo: what in the last build needs a person.

    hydra-ctl todo <dir> [--list [KIND]] [--format text|json]

Reads `.hydra/parsed/` (never builds). Kinds, in the order review walks them:
merges, references, placements, stale, contradictions,
verdicts. `--list` shows each open row with its id (what `answer` takes);
`--format json` gives the rows as data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from hydra import layout, resources
from hydra.cli import style

KINDS = ("merges", "references", "placements", "stale", "contradictions", "verdicts")


def kind_of(row: dict) -> str | None:
    """The review kind an open row belongs to, or None when nothing is asked."""
    st = row.get("status")
    if row.get("stale") or st == "confirmed-stale":
        return "stale"
    rel = row.get("rel")
    if rel == "sameAs" and st in ("proposed", "conflict"):
        return "merges"
    if rel == "references" and st in ("proposed", "unresolved"):
        return "references"
    if rel == "placedUnder" and st == "proposed":
        return "placements"
    if rel == "contradiction":
        return "contradictions"
    return None


def what(row: dict) -> str:
    rel = row.get("rel")
    if rel == "sameAs":
        g = f"  [group {row['group']}]" if row.get("group") else ""
        return f"{row.get('acap')} ~ {row.get('bcap')} — {row.get('criteria')}{g}"
    if rel == "references":
        n = len(row.get("candidates") or [])
        return f"{row.get('group')} \"{row.get('value')}\" — {row.get('status')}, {n} candidate{'s' if n != 1 else ''}"
    if rel == "placedUnder":
        return f"{row.get('subcap')} under {row.get('supcap')} — {row.get('criteria')}"
    if rel == "contradiction":
        return f"{row.get('a')} ~ {row.get('b')} — {row.get('criteria')}"
    return row.get("message", "")


COLUMNS = {"merges": ("row", "record", "record", "conflict", "group"),
           "references": ("row", "record", "field", "value", "candidates"),
           "placements": ("row", "record", "parent", "placed by"),
           "stale": ("row", "record", "record", "status"),
           "contradictions": ("row", "record", "record", "rejected"),
           "verdicts": ("row", "issue")}


def cells(kind: str, row: dict) -> list[str]:
    """One open row as the `--list` table's columns (COLUMNS[kind])."""
    if kind == "merges":
        return [row["id"], row.get("a") or "", row.get("b") or "",
                ", ".join(c["prop"] for c in row.get("conflicts") or []), row.get("group") or ""]
    if kind == "references":
        return [row["id"], row.get("record") or "", row.get("group") or "", str(row.get("value") or ""),
                str(len(row.get("candidates") or []))]
    if kind == "placements":
        return [row["id"], row.get("sub") or "", row.get("sup") or "", row.get("criteria") or ""]
    if kind == "stale":
        return [row["id"], row.get("a") or "", row.get("b") or "", row.get("status") or ""]
    if kind == "contradictions":
        return [row["id"], row.get("a") or "", row.get("b") or "", row.get("of") or ""]
    return [row["id"], row.get("message", "")]


def table(kind: str, rows: list[dict]) -> list[str]:
    """The `--list` lines for one kind: a header, then a row per line; a
    reference's candidates under it, one per line."""
    body = [cells(kind, r) for r in rows]
    w = [max(len(x) for x in col) for col in zip(COLUMNS[kind], *body)]
    line = lambda xs: "    " + "   ".join(f"{x:<{n}}" for x, n in zip(xs, w)).rstrip()
    out = [style.aside(line(COLUMNS[kind]))]
    for r, xs in zip(rows, body):
        out.append(style.aside(line(xs[:1])[:4 + w[0]]) + line(xs)[4 + w[0]:])
        cands = r.get("candidates") or []
        cw = max([len(str(c.get("caption"))) for c in cands] + [0])
        cs = max([len(str(c.get("schema"))) for c in cands] + [0])
        for n, c in enumerate(cands, 1):
            out.append(f"        {n}  " + style.name(f"{str(c.get('caption')):<{cw}}")
                       + style.aside(f"   {str(c.get('schema')):<{cs}}   {c.get('id')}"))
    return out


def collect(root) -> dict[str, list[dict]]:
    root = Path(root)
    if not (root / layout.BUILD_YAML).is_file():
        raise SystemExit(f"hydra: {root / layout.BUILD_YAML} not found; build the archive first")
    out: dict[str, list[dict]] = {k: [] for k in KINDS}
    for row in resources.read_jsonl(root / layout.IDENTICAL_JSONL) + resources.read_jsonl(root / layout.LEDGER_JSONL):
        k = kind_of(row)
        if k:
            out[k].append(row)
    summary = yaml.safe_load((root / layout.BUILD_YAML).read_text(encoding="utf-8")) or {}
    out["verdicts"] = [{"id": i["where"], "rel": "issue", "status": i["level"], "message":
                        f"{i['code']}: {i['message']}"} for i in summary.get("issues") or []
                       if i["code"].startswith("verdicts.")]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl todo",
                                 description="What in the last build needs a person.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    ap.add_argument("--list", nargs="?", const="all", choices=("all",) + KINDS, help="list the open rows")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(argv)
    todo = collect(resources.ensure_built(resources.archive(a.dir, read_only=True)))
    if (a.format == "json"):
        print(json.dumps({k: [{"id": r["id"], "status": r.get("status"), "what": what(r), "row": r}
                              for r in rows] for k, rows in todo.items()}, indent=1, ensure_ascii=False))
        return 0
    if not a.list:                                # the counts: what is open, by kind
        w = max(len(k) for k in todo)
        nw = max(len("open"), *(len(str(len(v))) for v in todo.values()))
        print(style.aside(f"  {'kind':<{w}}   {'open':>{nw}}"))
        for k, rows in todo.items():
            n = str(len(rows))
            print(f"  {k:<{w}}   " + (style.note(f"{n:>{nw}}") if rows else f"{n:>{nw}}"))
        return 0
    for k, rows in todo.items():                  # each kind with open rows: its count, then its table
        if a.list in ("all", k) and rows:
            print(style.name(k) + f"   {len(rows)}")
            for line in table(k, rows):
                print(line)
            print()
    return 0
