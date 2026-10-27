"""reset: remove review decisions from .hydra/review/verdicts.yaml.

    hydra-ctl reset [<dir>] [--only merges|placements|references|captions|stubs]
        [--yes] [--no-build]

Says what it will remove and where the backup goes, then waits: Enter
proceeds, anything else cancels (`--yes` skips the wait, for scripts). The
file is copied to `verdicts.yaml.<time>.bak` beside it first (a `.bak` is
never read as verdicts). Only the top verdicts file is reset; per-source files
under .hydra/review/<source>/ are left alone. Rebuilds unless --no-build."""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime

import yaml

from hydra import build, layout, resources
from hydra.cli import style
from hydra.cli.answer import set_verdict

KINDS = {"merges": ("merge-",), "placements": ("place-",), "references": ("ref-",), "captions": ("cap-",),
         "stubs": ("stub-",)}


def main(argv: list[str] | None = None, ask=input, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl reset", description="Remove review decisions.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    ap.add_argument("--only", choices=tuple(KINDS), default="")
    ap.add_argument("--yes", action="store_true", help="do not wait for Enter")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args(argv)
    root = resources.archive(a.dir)
    vfile = root / layout.VERDICTS
    doc = (yaml.safe_load(vfile.read_text(encoding="utf-8")) or {}) if vfile.is_file() else {}
    prefixes = KINDS[a.only] if a.only else tuple(p for ps in KINDS.values() for p in ps)
    keys = [k for k in doc if isinstance(k, str) and k.startswith(prefixes)]
    if not keys:
        say("no decisions to remove")
        return 0
    counts = {kind: sum(1 for k in keys if k.startswith(ps)) for kind, ps in KINDS.items()}
    backup = vfile.with_name(f"verdicts.yaml.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    say(f"This removes {len(keys)} decision(s) from {vfile}: "
        + ", ".join(f"{n} {k}" for k, n in counts.items() if n) + ".")
    say(f"A backup is written to {backup.name} first.")
    if not a.yes:
        try:
            got = ask("Press Enter to proceed, anything else cancels: ")
        except (EOFError, KeyboardInterrupt):
            got = "cancel"
        if got.strip():
            say("cancelled; nothing changed")
            return 1
    shutil.copy2(vfile, backup)
    for k in keys:
        set_verdict(vfile, k, None)
    say(f"{style.verb('Removed')} {style.plural(len(keys), 'decision')} from {style.path(vfile)} "
        + style.aside(f"(backup {backup.name})"))
    if not a.no_build:
        say(build.report(root, build.build_archive(root), verb="Rebuilt"))
    return 0
