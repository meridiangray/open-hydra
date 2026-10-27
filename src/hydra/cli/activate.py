"""activate / deactivate: name one archive so commands can leave out <dir>.

    hydra-ctl activate [<dir>]     with no dir: show the active archive
    hydra-ctl deactivate

The marker (`.hydra-activate`) is written in the current folder and found from
any folder below it, like `.git`."""
from __future__ import annotations

import argparse

from hydra import resources
from hydra.cli import style


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl activate",
                                 description="Name the archive commands use when <dir> is left out.")
    ap.add_argument("dir", nargs="?")
    a = ap.parse_args(argv)
    if not a.dir:
        act = resources.activated()
        print(act if act else "no active archive")
        return 0
    try:
        resources.activate(a.dir)
    except ValueError as e:
        raise SystemExit(f"hydra: {e}")
    print(f"{style.verb('Activated')} {style.path(resources.activated())}")
    return 0


def deactivate(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="hydra-ctl deactivate",
                            description="Remove the nearest activation marker.").parse_args(argv)
    try:
        active = resources.activated()
        marker = resources.deactivate()
        print(f"{style.verb('Deactivated')} {style.path(active)}" if active
              else f"{style.verb('Removed')} {style.path(marker)}")
    except ValueError as e:
        raise SystemExit(f"hydra: {e}")
    return 0
