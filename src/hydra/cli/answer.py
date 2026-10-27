"""answer: record one decision in `.hydra/review/verdicts.yaml`, then rebuild.

    hydra-ctl answer <dir> <id> <choice> [--no-build]

    merge-…   confirm | reject | clear      written with the row's basis, so the
                                            decision comes back if its evidence changes
    place-…   confirm | reject | clear
    ref-…     <n> | <record id> | none | clear
                                            n: a candidate's number in `todo --list`;
                                            none: the text names nothing here
    cap-<id>  <name> | clear                one of that node's own names

The id must be in the last build (`todo --list` shows them). Only that key's line
in verdicts.yaml is written or removed; the rest of the file, comments
included, is left as it is."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from hydra import build, layout, resources
from hydra.cli import style

_STATUS = {"confirm": "confirmed", "reject": "rejected"}


def _rows(root: Path) -> dict[str, dict]:
    rows = resources.review_rows(root)
    if not rows and not (root / layout.BUILD_YAML).is_file():
        raise SystemExit(f"hydra: {root} has no build; build the archive first")
    return rows


def value_for(root: Path, key: str, choice: str):
    """The verdict value `choice` means for `key`, or None for `clear`."""
    if choice == "clear":
        return None
    if key.startswith("cap-"):
        node = resources.declared_nodes(root).get(key[4:])
        if node is None:
            raise SystemExit(f"hydra: no node '{key[4:]}' in the last build")
        names = (node.get("props") or {}).get("name") or []
        if choice not in names:
            raise SystemExit(f"hydra: '{choice}' is not one of its names: {names}")
        return choice
    row = _rows(root).get(key)
    if row is None:
        raise SystemExit(f"hydra: no row '{key}' in the last build (see `todo --list`)")
    if key.startswith("merge-"):
        if choice not in _STATUS:
            raise SystemExit("hydra: a merge takes confirm, reject or clear")
        return {"status": _STATUS[choice], "basis": row.get("basis")} if row.get("basis") \
            else _STATUS[choice]
    if key.startswith("place-"):
        if choice not in _STATUS:
            raise SystemExit("hydra: a placement takes confirm, reject or clear")
        return _STATUS[choice]
    if key.startswith("ref-"):
        if choice == "none":
            return "none"                          # names nothing in this archive: not asked again
        cands = [c["id"] for c in row.get("candidates") or []]
        if choice.isdigit():
            n = int(choice)
            if not 1 <= n <= len(cands):
                raise SystemExit(f"hydra: pick 1..{len(cands)}")
            return cands[n - 1]
        known = set(cands) | {r for n in resources.declared_nodes(root).values() for r in n.get("referents") or []}
        if choice not in known:
            raise SystemExit(f"hydra: no record '{choice}' in the last build")
        return choice
    raise SystemExit(f"hydra: '{key}' is not an id answer takes")


def set_verdict(path: Path, key: str, value) -> str | None:
    """Write `key: value` (or remove the key when value is None) in a verdicts
    file, touching only that key's lines. Returns the line written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").split("\n") if path.is_file() else []
    out, i, head = [], 0, re.compile(rf"^{re.escape(key)}\s*:")
    while i < len(lines):
        if head.match(lines[i]):
            i += 1
            while i < len(lines) and lines[i][:1] in (" ", "\t") and lines[i].strip():
                i += 1                                    # the key's continuation lines
            continue
        out.append(lines[i])
        i += 1
    line = None
    if value is not None:
        if isinstance(value, dict):          # {status, basis} inline, on the key's one line
            line = f"{key}: " + yaml.safe_dump(value, sort_keys=False, default_flow_style=True,
                                               allow_unicode=True, width=10 ** 9).strip()
        else:
            line = yaml.safe_dump({key: value}, default_flow_style=False, allow_unicode=True,
                                  width=10 ** 9).strip()
        while out and out[-1] == "":
            out.pop()
        out.append(line)
    text = "\n".join(out).rstrip("\n") + "\n"
    parsed = yaml.safe_load(text) or {}
    if value is not None and parsed.get(key) != value or value is None and key in parsed:
        raise SystemExit(f"hydra: could not write {key} to {path} safely; file left unchanged")
    path.write_text(text, encoding="utf-8")
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl answer",
                                 description="Record one decision, then rebuild.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    ap.add_argument("id")
    ap.add_argument("choice", help="confirm | reject | clear, a candidate number or record id, or a name")
    ap.add_argument("--no-build", action="store_true", help="write the decision but do not rebuild")
    a = ap.parse_args(argv)
    root = resources.ensure_built(resources.archive(a.dir))
    value = value_for(root, a.id, a.choice)
    line = set_verdict(root / layout.VERDICTS, a.id, value)
    print(f"{style.verb('Recorded')} {line}" if line else f"{style.verb('Cleared')} {a.id}")
    if not a.no_build:
        print(build.report(root, build.build_archive(root), verb="Rebuilt"))
    return 0
