"""init: create an archive, or open a packed one into a new archive.

    hydra-ctl init <dir> [--name NAME]
    hydra-ctl init FILE.hydra

A `.hydra` file is opened into a folder named after it, beside it (new or
empty), and built there if the pack carries no build; the folder is then a live
archive like any other, and `pack` makes a new `.hydra` from it.

An empty or new folder becomes an archive; `--name` (default: the folder's
name) goes into `hydra.yaml`. At a terminal without `--name`, init asks for the
name (Enter keeps the folder's), then for the archive's id prefix (Enter takes
one made from the name; `none` keeps one prefix per collection, made from its
name). `--prefix` sets it without asking. The prefix is stored in `hydra.yaml`
and every collection without its own prefix uses it. A folder that is already an archive, or any other
non-empty folder, is refused (`defaults` shows an archive's settings)."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from hydra import layout, resources
from hydra.ingest import default_prefix, valid_prefix
from hydra.cli import style


def create(dest, name: str = "", prefix: str = "") -> Path:
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"hydra: {dest} exists and is not empty")
    shutil.copytree(resources.TEMPLATE, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    manifest = dest / layout.MANIFEST
    text = manifest.read_text(encoding="utf-8")
    name = name or dest.resolve().name
    value = name if re.fullmatch(r"[\w][\w .-]*", name) else json.dumps(name)   # JSON quoting is valid YAML
    text = re.sub(r"(?m)^name: .*$", lambda _: f"name: {value}" + (f"\nprefix: {prefix}" if prefix else ""),
                  text, count=1)
    manifest.write_text(text, encoding="utf-8")
    return dest


def ask_name(dest, ask) -> str:
    """The archive's name, asked once; Enter keeps the folder's name."""
    default = Path(dest).resolve().name
    return ask(f"Archive name [{default}]: ").strip() or default


def ask_prefix(name: str, ask, say) -> str:
    """The archive's id prefix: Enter takes one made from the name, `none` leaves
    each collection its own. Asked again until it is usable."""
    default = default_prefix(name)
    while True:
        got = ask(f"Id prefix [{default}] (none: one per collection): ").strip() or default
        if got == "none":
            return ""
        if valid_prefix(got):
            return got
        say("  lowercase letters, digits, '.', '_' and '-' only")


def main(argv: list[str] | None = None, say=print, ask=None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl init",
                                 description="Create an archive, or open a .hydra file into one.")
    ap.add_argument("dir", help="a new or empty folder, or a .hydra file to open")
    ap.add_argument("--name", default="", help="the archive's name in hydra.yaml (default: the folder's name)")
    ap.add_argument("--prefix", default="", help="the id prefix every collection uses unless it has its own")
    a = ap.parse_args(argv)
    if resources.is_pack(a.dir):
        if a.name or a.prefix:
            raise SystemExit("hydra: a .hydra carries its own name and prefix; --name and --prefix are for a new archive")
        from hydra.cli.pack import unpack
        dest, index = unpack(a.dir)
        say(f"{style.verb('Opened')} {a.dir} into {style.path(dest)} {style.aside('(%d files)' % len(index['files']))}")
        if not index.get("parsed"):
            resources.ensure_built(dest)
        return 0
    if resources.is_archive(a.dir):
        raise SystemExit(f"hydra: {a.dir} is already an archive "
                         f"(`hydra-ctl defaults {a.dir}` shows its settings)")
    if ask is None and sys.stdin.isatty() and sys.stdout.isatty():
        ask = input
    if a.prefix and not valid_prefix(a.prefix):
        raise SystemExit(f"hydra: {a.prefix!r} is not a usable prefix: lowercase letters, digits, '.', '_' and '-'")
    name = a.name or (ask_name(a.dir, ask) if ask else "")
    prefix = a.prefix or (ask_prefix(name or Path(a.dir).resolve().name, ask, say) if ask and not a.name else "")
    dest = create(a.dir, name, prefix)
    named = f" {style.name(json.dumps(name))}" if name and name != dest.resolve().name else ""
    say(f"{style.verb('Initialized')} empty Hydra archive{named} in {style.path(dest)}"
        + (" " + style.aside(f"(id prefix {prefix})") if prefix else ""))
    return 0
