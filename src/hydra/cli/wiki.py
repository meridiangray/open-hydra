"""wiki: read the universe as a wiki.

    hydra-ctl wiki [<dir> | FILE.hydra] serve [--port 8080] [--host 127.0.0.1] [--theme shore|dune|tide|tan|light]
    hydra-ctl wiki [<dir>] site -o DIR [--states c,p,d] [--publish]
    hydra-ctl wiki [<dir>] check [--format text|json]     what keeps the pages from being complete
    hydra-ctl wiki [<dir>] edges                          what the pages hold, and what draws each relationship
    hydra-ctl wiki [<dir>] badges                         the derived badge rules and how many pages each reaches
    hydra-ctl wiki [<dir>] sections                       the sections available, defined, and given to each page type
    hydra-ctl wiki [<dir>] define NAME --edge E [--side source|target] [--other SCHEMA] [--columns name,share,prop:tonnage]
                           [--sort period,-share] [--view table|list|timeline] [--title T] [--for Schema,Schema]
    hydra-ctl wiki [<dir>] define NAME --props birthDate,flag [--title T] [--for Schema]
    hydra-ctl wiki [<dir>] undefine NAME                  take a defined section out of wiki.yaml

One page per H, at `/e/<12 characters>`: the address never changes with the
H's state or flags (a full `H-d4-...` address answers 301 to it). A merged-away
H answers 301 to the H it went into; one whose records are all gone, 410 with
its last title. Pages are built from `universe/.parsed/` alone, by the
universe build, which runs first when the pages are older than what they are
built from. `serve` writes nothing else (a `.hydra` opens in a temporary view);
`site` writes a static copy to DIR, and with `--publish` moves every computed
H it wrote a page for to published, since a page someone can link to is a
promise its address will hold."""
from __future__ import annotations

import argparse
import sys

from hydra import resources
from hydra.cli import style
from hydra.universe import build as ubuild
from hydra.universe import layer, review
from hydra.wiki import site


def _pages(root, say):
    layer.read_manifest(root)
    if not ubuild.pages_current(root):
        print(style.aside("building the universe's pages first", sys.stderr), file=sys.stderr)
        ubuild.build(root)


def main(argv: list[str] | None = None, say=print) -> int:
    argv = list(argv or [])
    where = argv.pop(0) if argv and argv[0] not in ("serve", "site", "check", "edges", "sections", "badges", "define", "undefine") and resources.names_archive(argv[0]) else None
    ap = argparse.ArgumentParser(prog="hydra-ctl wiki", description="Read the universe as a wiki.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8080); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--theme", choices=tuple(site.THEMES), default=None,
                   help="default: wiki.yaml theme.base, else " + site.DEFAULT_THEME)
    s = sub.add_parser("site"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--states", default="c,p,d"); s.add_argument("--publish", action="store_true")
    s.add_argument("--theme", choices=tuple(site.THEMES), default=None,
                   help="default: wiki.yaml theme.base, else " + site.DEFAULT_THEME)
    s = sub.add_parser("check"); s.add_argument("--format", choices=("text", "json"), default="text")
    sub.add_parser("edges")
    sub.add_parser("badges")
    sub.add_parser("sections")
    s = sub.add_parser("define"); s.add_argument("name")
    s.add_argument("--edge"); s.add_argument("--side", choices=("source", "target")); s.add_argument("--other")
    s.add_argument("--verb"); s.add_argument("--former", choices=("yes", "no")); s.add_argument("--title")
    s.add_argument("--columns", help="comma list: name, verb, share, status, period, date, deal, prop:<property>, Label=<column>")
    s.add_argument("--sort"); s.add_argument("--view", choices=("table", "list", "timeline")); s.add_argument("--min", type=int)
    s.add_argument("--props", help="comma list of this page's own properties (instead of --edge)")
    s.add_argument("--for", dest="schemas", default="", help="comma list of page types that get the section")
    s.add_argument("--force", action="store_true", help="rewrite a wiki.yaml that has comments (kept as wiki.yaml.bak)")
    s = sub.add_parser("undefine"); s.add_argument("name"); s.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd in ("edges", "sections", "badges", "define", "undefine"):
        return _manage(a, where, say)
    if a.cmd == "check":
        import json
        from hydra.wiki import readiness
        root = resources.archive(where, read_only=True, built=False)
        _pages(root, say)
        found = readiness.check(root)
        if a.format == "json":
            say(json.dumps(found, indent=1, ensure_ascii=False))
            return 0
        for f in found:
            say(f"{f['level']:7} {f['count']:5}  {f['what']}")
            for x in f["examples"][:3]:
                say(style.aside(f"               {x}"))
            say(f"               do: {f['do']}")
        if not found:
            say("nothing missing: every page has what its records can give it")
        return 0
    if a.cmd == "serve":
        root = resources.archive(where, read_only=True, built=False)
        _pages(root, say)
        httpd, wiki = site.serve(root, a.port, a.host, a.theme)
        say(f"{style.verb('Serving')} {style.name(wiki.report['title'])}: {len(wiki.pages)} pages at "
            f"http://{a.host}:{httpd.server_address[1]}/  " + style.aside("(Ctrl+C stops)"))   # --port 0: the one the OS gave
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    root = resources.archive(where)
    _pages(root, say)
    states = tuple(x.strip() for x in a.states.split(",") if x.strip())
    out, emitted = site.site(root, a.out, states, a.theme)
    say(f"{style.verb('Wrote')} {len(emitted)} pages to {style.path(out)}")
    if a.publish:
        n = review.publish(root, emitted)
        say(f"{style.verb('Published')} {style.plural(n, 'computed H')}: their addresses hold from now on")
    return 0


def _column(text: str):
    """`share`, `prop:tonnage` or `Owner=name` / `Born=prop:birthDate` -> a column of a section definition."""
    label, _, col = text.rpartition("=")
    if col.startswith("prop:"):
        return {"label": label or col[5:], "prop": col[5:]}
    return {"label": label, "column": col} if label else col


def _manage(a, where, say) -> int:
    from hydra.wiki import manage
    root = resources.archive(where, read_only=a.cmd in ("edges", "sections", "badges"), built=False)
    _pages(root, say)
    w = site.Wiki(root)
    if a.cmd == "edges":
        for r in manage.edges(w):
            say(f"{r['count']:6}  {r['schema']:14} {r['edge']:16} {r['side']:7} {r['shown_by']:22} "
                + style.aside(f"other end: {r['other'] or '-'}"))
        return 0
    if a.cmd == "badges":
        for r in manage.badge_report(w):
            say(f"{r['pages']:6}  {r['key']:12} {r['group']:9} {r['icon']:12} " + style.aside(f"{r['label']}: {r['rule']}"))
        return 0
    if a.cmd == "sections":
        got = manage.sections(w)
        say("built in:  " + ", ".join(got["builtin"]))
        say("defined:   " + (", ".join(got["defined"]) or style.aside("none (hydra-ctl wiki define ...)")))
        say("")
        for schema, names in got["by_schema"].items():
            say(f"{schema:16} " + ", ".join(names))
        return 0
    if a.cmd == "undefine":
        for line in manage.undefine(root, a.name, a.force):
            say(f"{style.verb('Done')} {line}")
        return 0
    spec = {k: v for k, v in {
        "title": a.title, "view": a.view, "min": a.min,
        "sort": a.sort.split(",") if a.sort else None,
        "columns": [_column(x.strip()) for x in a.columns.split(",")] if a.columns else None,
        "props": [x.strip() for x in a.props.split(",")] if a.props else None,
        "relations": {k: v for k, v in {"edge": a.edge, "side": a.side, "other": a.other, "verb": a.verb,
                                         "former": {"yes": True, "no": False}.get(a.former)}.items() if v is not None} if a.edge else None,
    }.items() if v is not None}
    for line in manage.define(root, w, a.name, spec, [x.strip() for x in a.schemas.split(",") if x.strip()], a.force):
        say(f"{style.verb('Done')} {line}")
    return 0
