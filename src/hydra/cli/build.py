"""build: compile an archive, collections/ -> .hydra/parsed/.

    hydra-ctl build [<dir>] [--no-prefix] [--force] [--verbose]

Prints one line: the records, the entities they merged into, and the open
questions (`todo`), plus any errors or warnings (`check`); `--verbose` adds the
full summary (claims, reads, ledger). When nothing the build reads or writes has changed
since the last build (`freshness.up_to_date`), that build stands and its summary
is printed without building; `--force` builds anyway."""
from __future__ import annotations

import argparse

import yaml

from hydra import freshness, layout, resources, yamlcache



def report(root, summary: dict, seconds: float | None = None, verb: str = "Built") -> str:
    """The one line a build ends with: what went in, what came out, what is left."""
    from hydra.cli import style, todo
    left = sum(len(rows) for rows in todo.collect(root).values())
    counts = summary["issue_counts"]
    parts = [style.plural(summary["records"], "record"), style.plural(summary["entities"], "entity", "entities"),
             style.plural(left, "open question")]
    parts += [style.plural(counts[lv], lv) for lv in ("error", "warning") if counts.get(lv)]
    took = style.aside(f" ({seconds:.1f}s)") if seconds is not None else ""
    return f"{style.verb(verb)} {style.name(summary['name'])}: {', '.join(parts)}{took}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl build", description="Compile collections/ into .hydra/parsed/.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    ap.add_argument("--force", action="store_true", help="build even when nothing changed")
    ap.add_argument("--no-prefix", action="store_true", help="keep record ids as written, without prefixes")
    ap.add_argument("--verbose", action="store_true", help="also print the full summary (claims, reads, ledger)")
    a = ap.parse_args(argv)
    prefix = not a.no_prefix
    root = resources.archive(a.dir)
    if prefix and not a.force and freshness.up_to_date(root):   # nothing changed: the last build stands
        s = yaml.load((root / layout.BUILD_YAML).read_text(encoding="utf-8"), Loader=yamlcache._Loader)
    else:
        from hydra import build                                     # the compiler, only when it runs
        s = build.build_archive(root, prefix=prefix)
    print(report(root, s))
    if a.verbose:
        print(yaml.safe_dump({k: s[k] for k in ("records", "claims", "reads", "ledger", "issue_counts")},
                             sort_keys=False), end="")
    return 0
