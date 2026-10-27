"""positions: the position tree (the hierarchy rules) and the titles no rule places.

    hydra-ctl positions [<dir>] [--tree | --unplaced] [--nodes] [--read declared|generic]
        [--format text|json|mermaid] [--ascii]

Default: both. `--tree` is the position tree alone: each position under the one
above it, its titles listed under it, one per line (`outside` for a position
off the ladder, `implied` for one only the rules imply, `^` for one met a
second time). `--unplaced` is the titles seen in the data that no position
takes, in columns. `--nodes` adds, under each position, the records holding
it. `mermaid` draws the position graph. Never builds."""
from __future__ import annotations

import argparse
import json
import shutil
import sys

from hydra import resources
from hydra.cli import style

READS = ("declared", "generic")
UNPLACED_COLUMNS = 3


def render_tree(model: list[dict], ascii: bool = False) -> list[str]:
    """The position tree: a position per line, its titles (and with `--nodes`
    the records holding it) under it, aligned in a column."""
    tee, ell, vert = ("|-- ", "\\-- ", "|   ") if ascii else ("├── ", "└── ", "│   ")
    lines: list[str] = []

    def rec(n, prefix, conn):
        tags = [("   ", ""), ("outside", "aside")] if n.get("outside") else []
        tags += [("   ", ""), ("implied", "aside")] if n.get("source") == "implied" else []
        lines.append(style.aside(prefix + conn) + style.styled([(n["name"], "name")] + tags
                                                               + ([(" ^", "aside")] if n.get("dup") else [])))
        inner = prefix if not conn else prefix + ("    " if conn == ell else vert)
        side = vert[0] if n.get("children") else " "
        rows = [("titles", str(t), "") for t in n.get("titles") or []]
        rows += [("records", str(x["caption"]), x.get("schema") or "") for x in n.get("nodes") or []]
        last = None
        rw = max([len(str(x[1])) for x in rows if x[0] == "records"] + [0])
        for label, value, extra in rows:
            lab = label if label != last else ""
            last = label
            lines.append(style.aside(f"{inner}{side} {lab:<7}  ") + (
                style.accent(value) if label == "titles" else f"{value:<{rw}}   " + style.aside(extra)).rstrip())
        for i, c in enumerate(n.get("children") or []):
            rec(c, inner, ell if i == len(n["children"]) - 1 else tee)

    for r in model:
        rec(r, "", "")
    return lines


def render_unplaced(titles: list[str], width: int | None = None) -> list[str]:
    """The titles no position takes: a count, then the titles in columns, read down."""
    titles = [str(t) for t in titles]
    out = [style.aside("unplaced titles") + f"   {len(titles)}"]
    if not titles:
        return out
    width = width or shutil.get_terminal_size((120, 24)).columns
    cols = UNPLACED_COLUMNS
    while cols > 1:                               # as many columns as fit, each as wide as its longest
        per = -(-len(titles) // cols)
        ws = [max(len(t) for t in titles[c * per:(c + 1) * per]) for c in range(cols) if titles[c * per:]]
        if 2 + sum(ws) + 3 * (len(ws) - 1) <= width:
            break
        cols -= 1
    per = -(-len(titles) // cols)
    ws = [max(len(t) for t in titles[c * per:(c + 1) * per]) for c in range(cols) if titles[c * per:]]
    for i in range(per):
        row = [titles[j] for j in range(i, len(titles), per)]
        out.append(("  " + "   ".join(f"{t:<{ws[k]}}" for k, t in enumerate(row))).rstrip())
    return out


def render(model: list[dict], unrelated: list[str], issues: list, show_tree: bool = True,
           show_unplaced: bool = True, ascii: bool = False) -> str:
    lines = render_tree(model, ascii) if show_tree else []
    if show_unplaced:
        lines += ([""] if lines else []) + render_unplaced(unrelated)
    if issues:
        lines += ["", style.aside("issues")] + [f"  {i}" for i in issues]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from hydra import tree
    from hydra.shape.rules import rules_mermaid
    ap = argparse.ArgumentParser(prog="hydra-ctl positions",
                                 description="The position tree, and the titles no position takes.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--tree", action="store_true", help="the position tree only")
    which.add_argument("--unplaced", action="store_true", help="the unplaced titles only")
    ap.add_argument("--nodes", action="store_true", help="list the records holding each position")
    ap.add_argument("--read", choices=READS, default="declared")
    ap.add_argument("--format", choices=("text", "json", "mermaid"), default="text")
    ap.add_argument("--ascii", action="store_true", help="|-- \\-- | instead of box-drawing")
    a = ap.parse_args(argv)
    root = resources.ensure_built(resources.archive(a.dir, read_only=True))
    ir, parsed = tree._load(root, a.read)
    if a.format == "mermaid":
        sys.stdout.write(rules_mermaid(parsed, label=root.name))
        return 0
    model = tree.position_tree(ir, parsed if a.read == "declared" else None, with_nodes=a.nodes)
    unrelated = (ir.get("report") or {}).get("unrelated_titles") or []
    issues = parsed.get("issues") or []
    if a.format == "json":
        print(json.dumps({"tree": [] if a.unplaced else model, "unrelated": [] if a.tree else unrelated,
                          "issues": issues}, indent=1, ensure_ascii=False))
        return 0
    sys.stdout.write(render(model, unrelated, issues, show_tree=not a.unplaced, show_unplaced=not a.tree,
                            ascii=a.ascii))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
