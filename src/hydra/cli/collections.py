"""collections: each collection and its id prefix.

    hydra-ctl collections [<dir>]
    hydra-ctl collections prefix [<dir>] <collection> <prefix> [--rekey] [--no-build]

With no action: each collection, its prefix (the `<prefix>:` its ids are
namespaced with), whether that prefix is the archive's, chosen in
`collections/manifest.json` or made from the collection's name, its records,
and how many of them carry their own `prefix:` (those keep it whatever the prefix).

`prefix` stores a new prefix in the manifest. Every id the old prefix made
changes with it, and so do the decisions filed under those ids. When there are
any, it refuses unless `--rekey`, which rewrites them: each decision's key is
recomputed from the row of the last build it was made on (that build is run
first), its value and basis kept. A decision with no row in the last build
cannot be traced and is left as it is. Rebuilds unless --no-build."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from hydra import build, layout, resources
from hydra.cli import style
from hydra.cli.answer import set_verdict
from hydra.ingest import RESERVED_SOURCES, parse_records, resolve_prefixes, source_of
from hydra.review import ids, verdicts as vd

USAGE = ("usage: hydra-ctl collections [<dir>]\n"
         "       hydra-ctl collections prefix [<dir>] <collection> <prefix> [--rekey] [--no-build]")


def collections(root) -> dict[str, Path]:
    return {f.stem: f for f in resources.record_files(root)[0]}


def _manifest(root) -> dict:
    p = Path(root) / layout.COLLECTIONS_MANIFEST
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _records(path: Path) -> list[dict]:
    return parse_records(path.read_text(encoding="utf-8"))


def show(root, say) -> int:
    """Each collection: its prefix, its records and how many carry their own
    prefix, and from the last build its claims, entities another collection
    also supplied, and citations. Where the prefixes are set (the archive's,
    the manifest, the collection's name) is one line when it is the same for all."""
    cols = collections(root)
    if not cols:
        say("no collections")
        return 0
    man = _manifest(root)
    prefixes = resolve_prefixes(cols, man, resources.archive_prefix(root))
    chosen = {c for c, v in (man.get("collections") or {}).items() if isinstance(v, dict) and v.get("prefix")}
    bp = Path(root) / layout.BUILD_YAML
    built = ((yaml.safe_load(bp.read_text(encoding="utf-8")) or {}).get("collections") or {}) if bp.is_file() else {}
    where = {c: "archive" if prefixes[c] == resources.archive_prefix(root) else "manifest" if c in chosen
             else "name" for c in cols}
    one = len(set(where.values())) == 1
    n = lambda x: f"{x:,}" if isinstance(x, int) else "-"
    rows = []
    for c, f in cols.items():
        recs = _records(f)
        b = built.get(c) or {}
        rows.append([c, prefixes[c]] + ([] if one else [where[c]])
                    + [n(len(recs)), n(sum(1 for r in recs if source_of(r.get("id")))),
                       n(b.get("claims")), n(b.get("in_others")), n(b.get("citations"))])
    head = ["collection", "prefix"] + ([] if one else ["set in"]) + ["records", "own prefix", "claims", "in others",
                                                                     "citations"]
    left = 3 if not one else 2                    # text columns; the rest are numbers
    w = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "  " + "   ".join(f"{x:<{w[i]}}" if i < left else f"{x:>{w[i]}}" for i, x in enumerate(r))
    if one:
        say(style.aside("  prefixes set in") + f"   {next(iter(where.values()))}")
        say("")
    say(style.aside(line(head)))
    for r in rows:
        say(line(r))
    return 0


def rekey_plan(root, ren) -> tuple[list[tuple], list[str]]:
    """-> (moves [(file, old key, new key, new value)], keys with no row to trace).
    `ren(id)` is the id under the new prefix (unchanged for any other id)."""
    rows = resources.review_rows(root)
    moves, untraced = [], []
    for f in vd.files(root):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for k, v in (doc.items() if isinstance(doc, dict) else ()):
            if not isinstance(k, str):
                continue
            new, val = k, v
            if k.startswith("cap-"):
                new = ids.caption_key(ren(k[len("cap-"):]))
            elif k in rows:
                r = rows[k]
                if r["rel"] == "sameAs":
                    new = ids.merge_key(ren(r["a"]), ren(r["b"]))
                elif r["rel"] == "placedUnder":
                    new = ids.place_key(ren(r["sub"]), ren(r["sup"]))
                elif r["rel"] == "references":
                    new = ids.reference_key(ren(r["record"]), r["prop"], ren(r["value"]))
                    if isinstance(v, str):
                        val = ren(v)                   # a pin names a record id
            elif k.startswith(("merge-", "place-", "ref-")):
                untraced.append(k)
            if new != k or val != v:
                moves.append((f, k, new, val))
    return moves, untraced


def set_prefix(root, coll: str, prefix: str, rekey: bool, no_build: bool, say) -> int:
    cols = collections(root)
    if coll not in cols:
        raise SystemExit(f"hydra: no collection {coll!r} (have: {', '.join(cols) or 'none'})")
    if source_of(f"{prefix}:x") != prefix:
        raise SystemExit(f"hydra: {prefix!r} is not a usable prefix: lowercase letters, digits, "
                         "'.', '_' and '-', up to 64, not one of " + ", ".join(sorted(RESERVED_SOURCES)))
    man = _manifest(root)
    prefixes = resolve_prefixes(cols, man, resources.archive_prefix(root))
    old = prefixes[coll]
    if prefix == old:
        say(f"{coll}'s prefix is already {prefix}")
        return 0
    taken = [c for c, t in prefixes.items() if t == prefix and c != coll]
    if taken:
        raise SystemExit(f"hydra: {prefix!r} is already the prefix of {taken[0]}")
    local = {r["id"] for r in _records(cols[coll]) if r.get("id") and not source_of(r["id"])}
    mapping = {f"{old}:{x}": f"{prefix}:{x}" for x in local}
    ren = lambda x: mapping.get(x, x) if isinstance(x, str) else x

    moves, untraced = [], []
    if any(vd.files(root)):
        verdicts, _ = vd.load(root)
        if verdicts:
            build.build_archive(root)             # the rows the decisions were made on, current
            moves, untraced = rekey_plan(root, ren)
    if moves and not rekey:
        say(f"{len(moves)} decision(s) are filed under {old}: ids; the new prefix would orphan them.")
        say("Run again with --rekey to rewrite them. Nothing changed.")
        return 1

    cfg = man.setdefault("collections", {})
    entry = cfg.get(coll) if isinstance(cfg.get(coll), dict) else {}
    cfg[coll] = {**entry, "prefix": prefix}
    (Path(root) / layout.COLLECTIONS_MANIFEST).write_text(build._dump_json(man), encoding="utf-8")
    for f, k, new, val in moves:
        set_verdict(f, k, None)
        set_verdict(f, new, val)
    say(f"{style.verb('Changed')} {style.name(coll)}'s prefix: {old} -> {style.name(prefix)}"
        + (style.aside(f" ({style.plural(len(moves), 'decision')} rewritten)") if moves else ""))
    if untraced:
        say(f"{len(untraced)} decision(s) have no row in the last build to trace them; left as they are "
            "(`check` lists any that no longer match)")
    if not no_build:
        say(build.report(root, build.build_archive(root), verb="Rebuilt"))
        if moves:
            rows = resources.review_rows(root)
            found = sum(1 for _, _, new, _ in moves if new in rows or new.startswith("cap-"))
            say(style.aside(f"{found} of {len(moves)} rewritten decisions found their rows"))
    return 0


def main(argv: list[str] | None = None, say=print) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        say(USAGE)
        return 0
    flags = {a for a in argv if a.startswith("--")}
    pos = [a for a in argv if not a.startswith("--")]
    if flags - {"--rekey", "--no-build"}:
        style.usage(USAGE)
    if pos and pos[0] == "prefix":
        args = pos[1:]
        if len(args) not in (2, 3):
            style.usage(USAGE)
        d, (coll, value) = (args[0] if len(args) == 3 else None), args[-2:]
        return set_prefix(resources.archive(d), coll, value, "--rekey" in flags, "--no-build" in flags, say)
    if len(pos) > 1:
        style.usage(USAGE)
    return show(resources.archive(pos[0] if pos else None, read_only=True), say)
