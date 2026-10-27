"""stubs: the names that link to no record, and graduating one into an entity.

    hydra-ctl stubs [<dir>] [--format text|json]
    hydra-ctl stubs graduate [<dir>] <name> [--as Schema] [--no-build]
    hydra-ctl stubs drop [<dir>] <name> [--no-build]

With no action: each name some link values hold that no record has (from the
last build), how many links name it, from which fields, and the most specific
schema all of them can point at (`fits`); then the names already graduated,
with the schema they were graduated as. `graduate` records the decision
`stub-<slug>: <Schema>` (default: what it fits) and rebuilds, so every link
with that name points at one entity, `stub:<slug>`. `drop` removes the
decision. `tree --stubs` shows where the names would land before graduating
any. See stubs.py."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from hydra import layout, resources, schema
from hydra import stubs as st
from hydra.cli import style
from hydra.cli.answer import set_verdict
from hydra.review import verdicts as vd

USAGE = ("usage: hydra-ctl stubs [<dir>] [--format text|json]\n"
         "       hydra-ctl stubs graduate [<dir>] <name> [--as Schema] [--no-build]\n"
         "       hydra-ctl stubs drop [<dir>] <name> [--no-build]")


def graduated(root) -> list[dict]:
    """The stubs the decisions graduate: [{slug, name, links, fields, as}], from
    the last build (the links that now point at each)."""
    root = Path(root)
    chosen = st.decided(vd.load(root)[0])
    if not chosen:
        return []
    p = root / layout.CLAIMS_JSONL
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if p.is_file() else []
    schema.load(root=root)
    names: dict[str, Counter] = {}
    links: dict[str, Counter] = {}
    for r in rows:
        if st.is_stub(r.get("record")) and r["prop"] == "name":
            names.setdefault(r["record"][len(st.PREFIX) + 1:], Counter())[r["value"]] += 1
            continue
        pdefs = schema.resolve(r["schema"])["props"] if r.get("schema") in schema.SCHEMA else {}
        if (pdefs.get(r["prop"]) or {}).get("type") == "entity" and st.slug(r["value"]) in chosen:
            links.setdefault(st.slug(r["value"]), Counter())[f"{r['schema']}.{r['prop']}"] += 1
    return [{"slug": s, "name": (names.get(s) or Counter({s: 1})).most_common(1)[0][0],
             "links": sum((links.get(s) or Counter()).values()), "fields": list(links.get(s) or []), "as": v}
            for s, v in sorted(chosen.items())]


def show(root, say, as_json: bool = False) -> int:
    open_, done = st.found(root), graduated(root)
    if as_json:
        say(json.dumps({"stubs": open_, "graduated": done}, indent=1, ensure_ascii=False))
        return 0
    rows = [[e["name"], str(e["links"]), " ".join(e["fields"]), e["fits"] or "-", "-"] for e in open_] + \
           [[e["name"], str(e["links"]), " ".join(e["fields"]), "", e["as"]] for e in done]
    if not rows:
        say("no stubs")
        return 0
    head = ["name", "links", "fields", "fits", "as"]
    w = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "  " + "   ".join(f"{x:>{w[i]}}" if i == 1 else f"{x:<{w[i]}}" for i, x in enumerate(r))
    say(style.aside(line(head).rstrip()))
    for r in rows:
        say(line(r).rstrip())
    return 0


def _rebuild(root, say) -> None:
    from hydra import build
    say(build.report(root, build.build_archive(root), verb="Rebuilt"))


def graduate(root, name: str, as_: str, no_build: bool, say) -> int:
    s = st.slug(name)
    found = {e["slug"]: e for e in st.found(root)}
    if s not in found:
        if s in st.decided(vd.load(root)[0]):
            raise SystemExit(f"hydra: '{name}' is already graduated (`stubs drop` undoes it)")
        raise SystemExit(f"hydra: no link names '{name}' without a record (`stubs` lists the names)")
    e = found[s]
    schema.load(root=root)
    sname = as_ or e["fits"]
    if not sname:
        raise SystemExit(f"hydra: the fields naming '{name}' ({' '.join(e['fields'])}) fit no one schema; "
                         f"pass --as")
    kind = next((k for k in schema.SCHEMA if k.lower() == sname.lower()), None)
    if not kind:
        raise SystemExit(f"hydra: no schema '{sname}'")
    if e["fits"] and not schema.is_a(kind, e["fits"]):
        raise SystemExit(f"hydra: a {kind} cannot be what {' '.join(e['fields'])} points at (it takes a {e['fits']})")
    set_verdict(root / layout.VERDICTS, st.key(name), kind)
    say(style.aside("  graduated") + f"   {e['name']}   " + style.aside(kind) + f"   {st.PREFIX}:{s}")
    if not no_build:
        _rebuild(root, say)
    return 0


def drop(root, name: str, no_build: bool, say) -> int:
    k = st.key(name)
    if k[len(st.KEY):] not in st.decided(vd.load(root)[0]):
        raise SystemExit(f"hydra: '{name}' is not graduated")
    set_verdict(root / layout.VERDICTS, k, None)
    say(style.aside("  dropped") + f"   {name}")
    if not no_build:
        _rebuild(root, say)
    return 0


def main(argv: list[str] | None = None, say=print) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    action = args.pop(0) if args and args[0] in ("graduate", "drop") else ""
    ap = argparse.ArgumentParser(prog=f"hydra-ctl stubs{' ' + action if action else ''}",
                                 usage=USAGE.removeprefix("usage: "))   # argparse adds its own "usage: "
    ap.add_argument("words", nargs="*")
    ap.add_argument("--as", dest="as_", default="", help="graduate: the schema (default: what the links fit)")
    ap.add_argument("--no-build", action="store_true", help="do not rebuild")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(args)
    words = list(a.words)
    lead = words.pop(0) if words and resources.names_archive(words[0]) and (not action or len(words) > 1) else None
    if not action:
        if words:
            style.usage(USAGE)
        return show(resources.ensure_built(resources.archive(lead, read_only=True)), say, (a.format == "json"))
    if len(words) != 1:
        style.usage(USAGE)
    root = resources.ensure_built(resources.archive(lead))
    if action == "graduate":
        return graduate(root, words[0], a.as_, a.no_build, say)
    return drop(root, words[0], a.no_build, say)


if __name__ == "__main__":
    raise SystemExit(main())
