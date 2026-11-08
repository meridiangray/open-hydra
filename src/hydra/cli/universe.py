"""universe: canonical ids (Hs) across this archive and its members.

    hydra-ctl universe [<dir>] init [--title T]           add universe/ (a new uid; the archive as `self`)
    hydra-ctl universe [<dir>] status                     members, Hs by state and flag, warnings
    hydra-ctl universe [<dir>] embed SOURCE --as NAME     snapshot another archive into universe/members/
    hydra-ctl universe [<dir>] link PATH --as NAME        a member outside the file, pinned to its hash
    hydra-ctl universe [<dir>] refresh NAME [SOURCE]      re-pin a linked member, or embed a snapshot again
    hydra-ctl universe [<dir>] remove NAME                take a member out (its Hs are kept, orphaned)
    hydra-ctl universe [<dir>] build [--no-pages]         every member + the H-table -> universe/.parsed/
    hydra-ctl universe [<dir>] review                     the name pairs left to decide
    hydra-ctl universe [<dir>] merge A B [--by WHO --source WHAT]     decide: one entity
    hydra-ctl universe [<dir>] reject A B [...]           decide: never one entity
    hydra-ctl universe [<dir>] split H REF [REF ...]      decide: those records are another entity
    hydra-ctl universe [<dir>] publish H [H ...] | --all  something outside points at them now
    hydra-ctl universe [<dir>] caption H [TEXT]           a universe caption pin (no TEXT: removed)
    hydra-ctl universe [<dir>] show H                     one H as the last build sees it

An H is `H-<state><flags>-<12 characters>`: state c computed (nothing promised:
a build derived it), p published, d decided; flags 8 redirected, 4 stale
(a decision's records changed), 2 conflict (its records disagree on a date or
gender), 1 orphaned (no record left). Compare Hs by the 12 characters: state
and flags change, the identity does not. A, B and H take an H, its 12
characters, or a record (`case:a1`, or `member/record` for another member).

`hydra-ctl build` gives Hs to a universe whose only member is the archive
itself; with other members, `universe build` reads them all. Only merge,
reject, split, publish and caption write universe/canon.jsonl or the
universe's pins; a build never does. Members are never written."""
from __future__ import annotations

import argparse
import json

from hydra import resources
from hydra.cli import style
from hydra.universe import build as ubuild
from hydra.universe import layer, members, review

SUBS = {"init", "status", "embed", "link", "refresh", "remove", "build", "review", "merge", "reject", "split",
        "publish", "caption", "show"}


def _ap() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="hydra-ctl universe", description="Canonical ids across members.")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("--title", default="")
    sub.add_parser("status")
    for name in ("embed", "link"):
        s = sub.add_parser(name); s.add_argument("source"); s.add_argument("--as", dest="name", required=True)
    s = sub.add_parser("refresh"); s.add_argument("name"); s.add_argument("source", nargs="?")
    s = sub.add_parser("remove"); s.add_argument("name")
    s = sub.add_parser("build"); s.add_argument("--no-pages", action="store_true")
    sub.add_parser("review")
    for name in ("merge", "reject"):
        s = sub.add_parser(name); s.add_argument("a"); s.add_argument("b")
        s.add_argument("--by", default=""); s.add_argument("--source", default="")
    s = sub.add_parser("split"); s.add_argument("h"); s.add_argument("records", nargs="+")
    s = sub.add_parser("publish"); s.add_argument("hs", nargs="*"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("caption"); s.add_argument("h"); s.add_argument("text", nargs="?")
    s = sub.add_parser("show"); s.add_argument("h")
    return ap


def _split_argv(argv):
    argv = list(argv or [])
    if argv and argv[0] not in SUBS and not argv[0].startswith("-") and resources.names_archive(argv[0]):
        return argv[0], argv[1:]
    return None, argv


def _say_build(r: dict, say) -> None:
    c = r["counts"]
    pages = f"{c['pages']} pages, " if c.get("pages") is not None else ""
    say(f"{style.verb('Built')} universe {style.name(r['title'])}: {pages}{style.plural(c['hs'], 'H')}  "
        f"states {c['by_state']}  flags {c['by_flag'] or 'none'}"
        + (f"  {c['proposed']} name pairs to review" if c.get("proposed") is not None else ""))
    for name, m in r["members"].items():
        say(f"  member {name:12} {m['kind']:5} {m['entities']:6} entities  {m['problem']}")
    for b in r["blocked"]:
        say(style.aside(f"  kept apart: {b['a']} / {b['b']} ({b['why']}), rejected earlier"))
    for w in r["warnings"]:
        style.warn(w)


def main(argv: list[str] | None = None, say=print) -> int:
    where, rest = _split_argv(argv)
    a = _ap().parse_args(rest)
    js = a.format == "json"
    read_only = a.cmd in ("status", "review", "show")
    root = resources.archive(where, read_only=read_only, built=False)

    if a.cmd == "init":
        say(f"{style.verb('Added')} a universe layer: {style.path(layer.init(root, a.title))}")
        return 0
    layer.read_manifest(root)                       # every other command needs the layer
    if a.cmd == "status":
        r = layer.read_parsed(root, "report.json")
        if js:
            say(json.dumps(r, indent=1, ensure_ascii=False))
        else:
            _say_build(r, say)
    elif a.cmd == "embed":
        say(f"{style.verb('Embedded')} {a.name}: {style.path(members.embed(root, a.source, a.name))}")
    elif a.cmd == "link":
        spec = members.link(root, a.source, a.name)
        say(f"{style.verb('Linked')} {a.name}: {spec['path']} " + style.aside(f"(sha256 {spec['sha256'][:12]})"))
    elif a.cmd == "refresh":
        say(f"{a.name}: {members.refresh(root, a.name, a.source)}")
    elif a.cmd == "remove":
        members.remove(root, a.name)
        say(f"{style.verb('Removed')} member {a.name}; its Hs are kept, without records")
    elif a.cmd == "build":
        r = ubuild.build(root, pages=not a.no_pages)
        say(json.dumps(r, indent=1, ensure_ascii=False)) if js else _say_build(r, say)
    elif a.cmd == "review":
        built = {r["body"]: r for r in layer.read_parsed(root, "canon.jsonl")}
        pairs = layer.read_parsed(root, "report.json").get("proposed")
        if pairs is None:
            raise SystemExit("hydra: the last universe build made no pages; run `universe build`")
        if js:
            say(json.dumps([[built[x], built[y]] for x, y in pairs], indent=1, ensure_ascii=False))
            return 0
        for x, y in pairs:
            say(f"{built[x]['h']}  {built[x]['title']}  ({built[x]['schema']})")
            say(f"{built[y]['h']}  {built[y]['title']}  ({built[y]['schema']})\n")
        say(f"{style.plural(len(pairs), 'pair')} share a name. Decide each: "
            "universe merge A B, or universe reject A B")
    elif a.cmd == "merge":
        say(f"{style.verb('Decided')} one entity: H-{review.merge(root, a.a, a.b, by=a.by, source=a.source)}; "
            "the next universe build shows it")
    elif a.cmd == "reject":
        x, y = review.reject(root, a.a, a.b, by=a.by, source=a.source)
        say(f"{style.verb('Decided')} two entities: H-{x} / H-{y}; the next universe build shows it")
    elif a.cmd == "split":
        old, new = review.split(root, a.h, a.records)
        say(f"{style.verb('Split')} H-{old}: {', '.join(a.records)} are now H-{new}; the next build shows it")
    elif a.cmd == "publish":
        built = [r["body"] for r in layer.read_parsed(root, "canon.jsonl")]
        bodies = built if a.all else [review.resolve({r["body"]: r for r in layer.read_parsed(root, "canon.jsonl")}, h)
                                      for h in a.hs]
        n = review.publish(root, bodies)
        say(f"{style.verb('Published')} {style.plural(n, 'H')} (their bodies are kept from now on)")
    elif a.cmd == "caption":
        body = review.caption(root, a.h, a.text)
        say(f"{style.verb('Pinned' if a.text else 'Unpinned')} the caption of H-{body}")
    elif a.cmd == "show":
        built = {r["body"]: r for r in layer.read_parsed(root, "canon.jsonl")}
        body = review.resolve(built, a.h)
        page = next((p for p in layer.read_parsed(root, "pages.jsonl", missing=[]) if p["body"] == body), None)
        say(json.dumps(page or built[body], indent=1, ensure_ascii=False))
    return 0
