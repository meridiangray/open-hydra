"""defaults: the template's config files, as this archive carries them.

    hydra-ctl defaults [<dir>]
    hydra-ctl defaults off [<dir>] [generic|hierarchy|hints ...]
    hydra-ctl defaults on [<dir>] [generic|hierarchy|hints ...]
    hydra-ctl defaults restore [<dir>] <name ...> | --all [--yes]

With no action: each default (generic, hierarchy, hints, direction, collate,
params, artifact) and whether it is as shipped, changed, missing or off.

`off` / `on` switch the hierarchy defaults (all three when none is named): an
`off` file is kept but the build and `check` read it as empty, for an archive
with a hierarchy of its own. The switch is `defaults_off:` in `hydra.yaml`. The
other defaults are what the compiler runs on and cannot be switched off.

`restore` copies the shipped file(s) back. It says what it replaces, backs up
every changed file beside it (`<file>.<time>.bak`), then waits: Enter
proceeds, anything else cancels (`--yes` skips the wait). It does not rebuild."""
from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

from hydra import layout, resources
from hydra.cli import style

ACTIONS = ("off", "on", "restore")
USAGE = ("usage: hydra-ctl defaults [off|on|restore] [<dir>] [<name> ...] "
         "[--all] [--yes]\n  names: " + ", ".join(resources.DEFAULTS))


def _args(argv):
    action = argv[0] if argv and argv[0] in ACTIONS else ""
    rest = argv[1:] if action else argv
    flags = {a for a in rest if a.startswith("--")}
    if flags - {"--all", "--yes"} or "-h" in rest:
        style.usage(USAGE)
    pos = [a for a in rest if not a.startswith("--")]
    names = [a for a in pos if a in resources.DEFAULTS]
    dirs = [a for a in pos if a not in resources.DEFAULTS]
    if len(dirs) > 1:
        raise SystemExit(f"hydra: unknown default(s) {', '.join(dirs[1:])}\n{USAGE}")
    return action, (dirs[0] if dirs else None), names, flags


def set_off(root, off: set[str]) -> None:
    """Write `defaults_off:` in hydra.yaml (removed when empty), touching only that line."""
    m = Path(root) / layout.MANIFEST
    lines = [l for l in m.read_text(encoding="utf-8").split("\n")
             if not re.match(rf"^{resources.OFF_KEY}\s*:", l)]
    while lines and lines[-1] == "":
        lines.pop()
    if off:
        lines.append(f"{resources.OFF_KEY}: [{', '.join(n for n in resources.SWITCHABLE if n in off)}]")
    text = "\n".join(lines) + "\n"
    if resources.defaults_off_doc(yaml.safe_load(text) or {}) != off:
        raise SystemExit(f"hydra: could not write {resources.OFF_KEY} to {m} safely; file left unchanged")
    m.write_text(text, encoding="utf-8")


def status(root, say) -> int:
    for n in resources.DEFAULTS:
        d = resources.default_state(root, n)
        note = ""
        if n == "params" and d["state"] != "default":
            odd = [p for p, s in d["files"].items() if s != "default"]
            note = f"  ({len(odd)} of {len(d['files'])}: " + ", ".join(
                p.rsplit("/", 1)[-1].replace(".param.yaml", "") for p in odd[:6]) + (" …" if len(odd) > 6 else "") + ")"
        elif d["state"] == "off" and d["content"] != "default":
            note = f"  (file {d['content']})"
        say(f"{n:<10} {d['state']}{note}")
    return 0


def restore(root, names, yes, ask, say) -> int:
    files = [(rel, s) for n in names for rel, s in resources.default_state(root, n)["files"].items()
             if s != "default"]
    if not files:
        say("nothing to restore: " + ", ".join(names) + " as shipped")
        return 0
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    changed = [rel for rel, s in files if s == "changed"]
    say(f"This restores {len(files)} file(s) from the template: "
        + ", ".join(rel for rel, _ in files[:8]) + (" …" if len(files) > 8 else ""))
    if changed:
        say(f"{len(changed)} changed file(s) are backed up first, as <file>.{stamp}.bak")
    if not yes:
        try:
            got = ask("Press Enter to proceed, anything else cancels: ")
        except (EOFError, KeyboardInterrupt):
            got = "cancel"
        if got.strip():
            say("cancelled; nothing changed")
            return 1
    for rel, s in files:
        dest = root / rel
        if s == "changed":
            shutil.copy2(dest, dest.with_name(f"{dest.name}.{stamp}.bak"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resources.TEMPLATE / rel, dest)
    off = resources.defaults_off(root) & set(names)
    say(f"{style.verb('Restored')} {style.plural(len(files), 'file')} from the template"
        + (style.aside(f" (still off: {', '.join(sorted(off))})") if off else ""))
    return 0


def main(argv: list[str] | None = None, ask=input, say=print) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        say(USAGE)
        return 0
    action, d, names, flags = _args(argv)
    root = resources.archive(d, read_only=not action)
    if not action:
        return status(root, say)
    if action in ("off", "on"):
        bad = [n for n in names if n not in resources.SWITCHABLE]
        if bad:
            raise SystemExit(f"hydra: {', '.join(bad)} cannot be switched off: the compiler runs on it. "
                             f"Switchable: {', '.join(resources.SWITCHABLE)}")
        chosen = set(names or resources.SWITCHABLE)
        off = resources.defaults_off(root)
        off = off | chosen if action == "off" else off - chosen
        set_off(root, off)
        say(f"off: {', '.join(n for n in resources.SWITCHABLE if n in off) or 'none'}; build to apply")
        return 0
    if not names and "--all" not in flags:
        raise SystemExit("hydra: name what to restore, or --all\n" + USAGE)
    return restore(root, names or list(resources.DEFAULTS), "--yes" in flags, ask, say)
