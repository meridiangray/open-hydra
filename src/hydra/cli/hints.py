"""hints: the rules in .hydra/rules/hints.yaml, and linking an image file by one.

    hydra-ctl hints [<dir>]
    hydra-ctl hints set [<dir>] portrait|thumb|logo <image> [--schema S] [--position P]
        [--titled TEXT] [--name N] [--no-build]

With no action: each rule, numbered as `check` and the build name them, what it
matches, what it sets, and how many nodes it reached in the last build.

`set` links an image file to every entity a match picks. The image is copied
into .hydra/resources/ (portraits/, icons/ for a thumb, logos/), unless it is
already there (a path such as `icons/crown.svg` is looked for there too); a different file of the same name there is never overwritten.
The match takes only these keys, any of them together (all must hold):
`--schema` (is-a), `--position`, `--titled` (a title the data states contains
TEXT, a regular expression, accents and case set aside) and `--name` (the name
only). Anything wider is written in hints.yaml by hand. The rule is appended
to the end of the file, its comments untouched; if `check` finds an error or a
warning in it (an unknown schema or position, a bad pattern), the file is put
back as it was. Rebuilds unless --no-build, then says how many nodes it reached."""
from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

from hydra import layout, lint, resources, schema
from hydra.cli import style
from hydra.shape import rules
from hydra.structure import fold

FOLDER = {"portrait": "portraits", "thumb": "icons", "logo": "logos"}
IMAGE_TYPES = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif")
USAGE = ("usage: hydra-ctl hints [<dir>]\n"
         "       hydra-ctl hints set [<dir>] portrait|thumb|logo <image> [--schema S] [--position P]\n"
         "                           [--titled TEXT] [--name N] [--no-build]")


def flow(v) -> str:
    """One-line YAML, quoted wherever YAML needs it (a comma in a name stays in it)."""
    return yaml.safe_dump(v, default_flow_style=True, width=10**6, allow_unicode=True, sort_keys=False).strip()


def _hits(root: Path) -> dict[int, int] | None:
    """{rule index: nodes it put an image on} from the last build's declared read, or None unbuilt."""
    p = root / f"{layout.PARSED_DIR}/declared.json"
    if not p.is_file():
        return None
    nodes = (json.loads(p.read_text(encoding="utf-8")).get("nodes") or {}).values()
    out: dict[int, int] = {}
    for n in nodes:
        for i in {x["rule"] for k in rules.IMAGES for x in n.get(f"{k}s") or []}:
            out[i] = out.get(i, 0) + 1
    return out


def show(root: Path, say) -> int:
    doc = yaml.safe_load((root / layout.HINTS).read_text(encoding="utf-8")) if (root / layout.HINTS).is_file() else {}
    rows = (doc or {}).get("hints") or []
    if not rows:
        say(f"no rules in {layout.HINTS}")
        return 0
    hits = _hits(root)
    w = len(str(len(rows) - 1))
    for i, h in enumerate(rows):
        h = h if isinstance(h, dict) else {}
        n = (hits or {}).get(i)
        count = "" if hits is None else ("   " + style.aside("images on ") + str(n) if n else "")
        say(f"  {style.aside(f'{i:>{w}}')}  {flow(h.get('match'))}   {style.accent(flow(h.get('set')))}{count}")
    if hits is None:
        say(style.aside("  (not built: no counts)"))
    return 0


def place_image(root: Path, image: Path, kind: str) -> str:
    """The image's path inside .hydra/resources/, copying it there if it is not."""
    base = (root / layout.RESOURCES_DIR).resolve()
    src = image.expanduser().resolve()
    if not src.is_file() and not image.is_absolute() and (base / image).is_file():
        src = (base / image).resolve()            # a path inside .hydra/resources/, as the rules write it
    if not src.is_file():
        raise SystemExit(f"hydra: {image} not found (here or in {layout.RESOURCES_DIR}/)")
    if src.suffix.lower() not in IMAGE_TYPES:
        raise SystemExit(f"hydra: {image.name} is not an image ({', '.join(IMAGE_TYPES)})")
    if src.is_relative_to(base):
        return src.relative_to(base).as_posix()
    dest = base / FOLDER[kind] / src.name
    if dest.exists() and not filecmp.cmp(src, dest, shallow=False):
        raise SystemExit(f"hydra: a different {dest.name} is already in {layout.RESOURCES_DIR}/{FOLDER[kind]}/; "
                         "rename your file, or point at the one there")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(src, dest)
    return dest.relative_to(base).as_posix()


def set_rule(root: Path, kind: str, image: Path, match: dict, no_build: bool, say) -> int:
    if not match:
        raise SystemExit("hydra: say which entities: --schema, --position, --titled and/or --name")
    if "titled" in match:
        try:
            re.compile(match["titled"]["contains"])
        except re.error as e:
            raise SystemExit(f"hydra: --titled is not a valid regular expression: {e}")
    hp = root / layout.HINTS
    before = hp.read_text(encoding="utf-8") if hp.is_file() else ""
    old = (yaml.safe_load(before) or {}) if before.strip() else {}
    if not isinstance(old, dict) or not isinstance(old.get("hints") or [], list):
        raise SystemExit(f"hydra: {layout.HINTS} is not a `hints:` list; fix it first (`check` says how)")
    rows = old.get("hints") or []
    path = place_image(root, image, kind)
    rule = {"match": match, "set": {kind: path}}
    for i, h in enumerate(rows):
        if h == rule:
            say(f"{style.aside('already there')} as hints[{i}]: {flow(match)}   {flow(rule['set'])}")
            return 0
    if not before.strip():
        text = "hints:\n"
    elif "hints" not in old:
        text = before.rstrip("\n") + "\nhints:\n"
    else:
        text = before if before.endswith("\n") else before + "\n"
    text += f"  - match: {flow(match)}\n    set:   {flow(rule['set'])}\n"
    new = yaml.safe_load(text) or {}
    i = len(rows)
    if (new.get("hints") or [])[:-1] != rows or (new.get("hints") or [None])[-1] != rule:
        raise SystemExit(f"hydra: {layout.HINTS} does not end with its `hints:` list, so the rule cannot be "
                         f"added safely; add it under `hints:` by hand:\n  - match: {flow(match)}\n"
                         f"    set:   {flow(rule['set'])}")
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(text, encoding="utf-8")
    schema.load(root=root)
    fam = root / layout.DIRECTION
    found = [x for x in lint.check(root, fold.load_direction(fam if fam.is_file() else None))
             if x["file"] == layout.HINTS and x["where"] == f"hints[{i}]" and x["level"] in ("error", "warning")]
    if found:
        hp.write_text(before, encoding="utf-8") if before else hp.unlink()
        raise SystemExit("hydra: not added, " + "; ".join(x["message"] for x in found))
    say(f"{style.verb('Added')} hints[{i}]: {flow(match)}   {style.accent(flow(rule['set']))}")
    if "hints" in resources.defaults_off(root):
        style.warn("hints are switched off in hydra.yaml (`defaults on hints`): the rule is not read")
        return 0
    if not no_build:
        from hydra import build
        say(build.report(root, build.build_archive(root), verb="Rebuilt"))
        n = (_hits(root) or {}).get(i, 0)
        say(f"  {style.aside('reaches')}   {n} {'node' if n == 1 else 'nodes'}" if n else
            f"  {style.note('matches nobody yet')}: check the spelling, or `node find` the entity")
    return 0


def main(argv: list[str] | None = None, say=print) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    action = args.pop(0) if args and args[0] == "set" else ""
    ap = argparse.ArgumentParser(prog=f"hydra-ctl hints{' set' if action else ''}",
                                 usage=USAGE.removeprefix("usage: "))   # argparse adds its own "usage: "
    ap.add_argument("words", nargs="*")
    ap.add_argument("--schema", default="", help="set: entities of this type (and its subtypes)")
    ap.add_argument("--position", default="", help="set: entities in this position")
    ap.add_argument("--titled", default="", help="set: a title the data states contains this (a regular expression)")
    ap.add_argument("--name", default="", help="set: the entity's name (aliases are not read)")
    ap.add_argument("--no-build", action="store_true", help="set: do not rebuild")
    a = ap.parse_args(args)
    words = list(a.words)
    lead = words.pop(0) if words and resources.names_archive(words[0]) else None
    if not action:
        if words:
            style.usage(USAGE)
        return show(resources.archive(lead, read_only=True), say)
    if len(words) != 2 or words[0] not in FOLDER:
        style.usage(USAGE)
    match = {k: v for k, v in (("schema", a.schema), ("position", a.position),
                                ("titled", {"contains": a.titled} if a.titled else ""), ("name", a.name)) if v}
    return set_rule(resources.archive(lead), words[0], Path(words[1]), match, a.no_build, say)


if __name__ == "__main__":
    raise SystemExit(main())
