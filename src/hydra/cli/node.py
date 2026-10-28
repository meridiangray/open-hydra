"""node find: one value in, the closest nodes out.

    hydra-ctl node find [<dir>] [type] <value> [--type T] [--field name|id|identifier|value|any]
        [--limit N] [--min SCORE] [--read declared|generic] [--format text|json]

Words that name a type (`person`, `Company`, any capitalisation) keep that type
and its subtypes; the rest is the value, in any order (`node find person tikrit`).

Scores every node of the last build against the value (never builds):

    1.00  a name equals it (case, accents and punctuation ignored)
    0.90+ a name contains all its words
    1.00  an identifier equals it, after that identifier's normalization
    0.85  it is part of the node's id, or of an id merged into it
    0.80  another field's value equals it; 0.75 one holds all its words
    else  difflib's similarity to the closest name (typos still find)

Names are every `name`, `alias`, `weakAlias` and `previousName` value merged into
the node; "another field" is any other property (`birthPlace`, `address`, ...).
Display only: nothing here decides a merge."""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from hydra import layout, query, resources, schema
from hydra import sources as sources_mod
from hydra.cli import style
from hydra.identity import types

NAMES = ("name", "alias", "weakAlias", "previousName")
READS = layout.READS


def score_node(n: dict, q: str, prop_types: dict, field: str = "any", search: str = "all") -> tuple[float, str, str]:
    """(score, field, value) of the node's best match for query `q`; `search`
    (query.SEARCH) narrows `any`: `names` to names and ids, `no-text` to every
    field but free text."""
    if search == "names" and field == "any":
        return max(score_node(n, q, prop_types, "name"), score_node(n, q, prop_types, "id"), key=lambda x: x[0])
    best = (0.0, "", "")
    qn, qw = types.name_key(q)
    props = n.get("props") or {}
    if field in ("any", "name") and qn:
        for p in NAMES:
            for v in props.get(p) or []:
                vn, vw = types.name_key(v)
                if not vn:
                    continue
                if vn == qn:
                    s = 1.0
                elif qw and qw <= vw:
                    s = 0.9 + 0.1 * len(qw) / len(vw)
                else:
                    s = _words_score(qw, vw)
                if s > best[0]:
                    best = (s, p, v)
    if field in ("any", "identifier"):
        for p, vals in props.items():
            t = prop_types.get(p)
            if t in types.EXACT_TYPES:
                norm = types.NORMALIZERS[t]
                if norm(q) and any(norm(v) == norm(q) for v in vals):
                    return 1.0, p, next(v for v in vals if norm(v) == norm(q))
    if field in ("any", "value") and qn and best[0] < 0.8:
        for p in sorted(props):
            if p in NAMES or prop_types.get(p) in types.EXACT_TYPES or prop_types.get(p) == "entity":
                continue
            if search == "no-text" and prop_types.get(p) == "text":
                continue
            for v in props.get(p) or []:
                if not isinstance(v, str):
                    continue
                vn, vw = types.name_key(v)
                s = 0.8 if vn == qn else 0.75 if qw and qw <= vw else 0.0
                if s > best[0]:
                    best = (s, p, v)
    if field in ("any", "id") and len(q) >= 3:
        ql = q.lower()
        for rid in [n.get("id", "")] + list(n.get("referents") or []):
            target = rid.lower() if ":" in ql else rid.lower().split(":", 1)[-1]   # the prefix is not the id
            if ql == target:
                return 1.0, "id", rid
            if ql in target and best[0] < 0.85:
                best = (0.85, "id", rid)
    return best


def _words_score(qw: frozenset, vw: frozenset) -> float:
    """Word-by-word closeness: each query word against its closest word in the
    value (difflib), averaged; extra words in the value cost a little."""
    if not qw or not vw:
        return 0.0
    each = [max(difflib.SequenceMatcher(None, q, v).ratio() for v in vw) for q in qw]
    return sum(each) / len(each) * (0.85 + 0.15 * min(1.0, len(qw) / len(vw)))


def find(root, q: str, kind="", field: str = "any", limit: int = 10,
         min_score: float = 0.6, read: str = "declared", search: str = "all") -> list[dict]:
    """`kind`: one schema name or a list of them (any capitalisation)."""
    root = Path(root)
    p = root / READS[read]
    if not p.is_file():
        raise SystemExit(f"hydra: {p} not found; build the archive first")
    ir = json.loads(p.read_text(encoding="utf-8"))
    nodes, ptypes = ir.get("nodes") or {}, ir.get("prop_types") or {}
    kinds = [kind] if isinstance(kind, str) and kind else list(kind or [])
    if kinds:
        schema.load(root=root)
        kinds, _ = query.split(kinds)
    hits = []
    for rid, n in nodes.items():
        if not query.of_type(n.get("schema", ""), kinds):
            continue
        s, f, v = score_node(n, q, ptypes, field, search)
        if s >= min_score:
            parent = nodes.get(n.get("pid") or "") or {}
            hits.append({"score": round(s, 3), "id": rid, "caption": n.get("caption"),
                         "schema": n.get("schema"), "position": n.get("position"),
                         "parent": parent.get("caption"), "matched": {"field": f, "value": v}})
    hits.sort(key=lambda h: (-h["score"], str(h["caption"]).lower(), h["id"]))
    return hits[:limit] if limit else hits


COLUMNS = ("score", "name", "schema", "id", "position", "parent", "matched")
SHOWN = 50                                       # a matched value longer than this is cut, with …


def table(hits: list[dict]) -> list[str]:
    """One hit per line, in columns; `matched` is the field and value that
    matched, left out when it is the caption itself."""
    def cells(h):
        m = h["matched"]
        v = str(m["value"])
        v = v if len(v) <= SHOWN else v[:SHOWN - 1] + "…"
        hit = "" if m["field"] == "name" and m["value"] == h["caption"] else f"{m['field']}  {v}"
        return [f"{h['score']:.2f}", str(h["caption"]), str(h["schema"]), h["id"], h["position"] or "",
                h["parent"] or "", hit]
    body = [cells(h) for h in hits]
    if not body:
        return []
    w = [max(len(x) for x in col) for col in zip(COLUMNS, *body)]
    kinds = ("aside", "name", "aside", "aside", "accent", "", "aside")
    line = lambda xs, ks: style.styled([(f"{x:<{n}}" + ("   " if i < len(xs) - 1 else ""), k)
                                        for i, (x, n, k) in enumerate(zip(xs, w, ks))]).rstrip()
    return [style.aside(line(COLUMNS, [""] * len(COLUMNS)))] + [line(xs, kinds) for xs in body]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != "find":
        style.usage("usage: hydra-ctl node find [<dir>] [type] <value> [options]   (--help for them)")
    f = argparse.ArgumentParser(prog="hydra-ctl node find", description="One value in, the closest nodes out.")
    f.add_argument("words", nargs="+", metavar="[dir] [type] value",
                   help="an archive (optional), then types and the value, in any order")
    f.add_argument("--type", default="", help="this schema and its subtypes, any capitalisation")
    f.add_argument("--field", choices=("any", "name", "id", "identifier", "value"), default="any",
                   help="where to look: names, ids, identifiers, other field values, or all")
    f.add_argument("--limit", type=int, default=10, help="at most this many (0: all)")
    f.add_argument("--min", type=float, default=0.6, help="lowest score shown, 0..1")
    f.add_argument("--read", choices=tuple(READS), default="declared")
    f.add_argument("--format", choices=("text", "json"), default="text")
    query.add_search_flags(f)
    a = f.parse_intermixed_args(argv[1:])
    words = list(a.words)
    lead = words.pop(0) if len(words) > 1 and resources.names_archive(words[0]) else None
    root = resources.ensure_built(resources.archive(lead, read_only=True))
    schema.load(root=root)
    words, with_sources = sources_mod.take_word(words)        # `node find wal sources`
    kinds, text = query.split(words, a.type)
    if not text:
        raise SystemExit("hydra: node find needs a value to look for (a type alone only narrows it)")
    hits = find(root, text, kinds, a.field, a.limit, a.min, a.read, query.search_mode(root, a))
    if (a.format == "json"):
        print(json.dumps({"hits": hits, "sources": sources_mod.show_for(root, [h["id"] for h in hits], "json")}
                         if with_sources else hits, indent=1, ensure_ascii=False))
        return 0
    if not hits:
        print("no match")
    for line in table(hits):
        print(line)
    if with_sources and hits:
        sources_mod.show_for(root, [h["id"] for h in hits])
    return 0
