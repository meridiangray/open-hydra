"""claims.py — where each value of an entity came from, from the last build.

    hydra-ctl claims [<dir>] <name> [<name> ...]
        [--type T] [--prop P] [--collection C] [--exact] [--format text|json]
    ... claims summary [<dir>] [--format text|json]

A claim is one row of `.hydra/parsed/claims.jsonl`: `{entity, record, prop, value,
schema, collection, source}`, one per value a record supplied for a merged entity.
The lookup matches entities whose name, alias, weak alias or previous name equals
`<name>` or contains all its words (case, accents and punctuation ignored;
`--exact`: equal only), or whose id or merged-away id is `<name>`. `--type` keeps
that FtM schema and its subtypes. Each entity is one block, grouped by property:
one line per distinct value with the collections that supplied it, `≠` where
collections disagree. Under each value, its trail: the records that supplied it
and the pages their `sources` point at ("Case file p.3"), and every review row it
took part in: a merge whose `conflicts` name it, a contradiction it helped
cause, with the row's status and whether that status is your decision. Each
entity also lists the documents linked to it as a whole (`Documentation`).
`summary` counts claims per collection, schema and property, and
shows where collections disagree on an identity field.
Never builds. Ported from the original hydra's `claims`."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from hydra import layout, query, resources, schema
from hydra import sources as sources_mod
from hydra.cli import style
from hydra.identity import classify, types
from hydra.review import verdicts as vd


def load(root) -> list[dict]:
    p = Path(root) / layout.CLAIMS_JSONL
    if not p.is_file():
        raise SystemExit(f"hydra: {p} not found; build the archive first")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


NAMES = ("name", "alias", "weakAlias", "previousName")
SHOWN = 10


def _distinct(root, schema_name: str) -> set:
    """The distinct-category properties of a schema (params applied): the ones
    whose disagreement is a real conflict, as in the merge."""
    if schema_name not in schema.SCHEMA:
        return set()
    params = Path(root) / layout.PARAMS_DIR
    return {p for p, pc in classify.classify(schema_name, params if params.is_dir() else None).items()
            if pc.distinct}


def _prop_types(root) -> dict:
    p = Path(root) / layout.READS["declared"]
    return json.loads(p.read_text(encoding="utf-8")).get("prop_types") or {} if p.is_file() else {}


# ---- trails: from a value to its records, their evidence, and the review ------

DOC_TITLE = ("title", "fileName", "name")


class Trails:
    """What a value's trail needs, read once: which entity each record ended up
    in, the props of every entity (to describe pages and documents), each
    record's `sources`, the review rows, and which rows carry your decision."""
    def __init__(self, root, rows: list[dict], nodes: dict, ptypes: dict):
        root = Path(root)
        self.nodes, self.norm = nodes, same_value(ptypes)
        self.entity_of = {r["record"]: r["entity"] for r in rows if r.get("record")}
        self.collection_of = {r["record"]: r.get("collection", "") for r in rows if r.get("record")}
        self.props: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        self.cited: dict[str, list] = defaultdict(list)
        self.named: dict[str, str] = {}               # record -> the first name it gives
        for r in rows:
            self.props[r["entity"]][r["prop"]].append(r["value"])
            if r["prop"] == "sources" and r.get("record"):
                self.cited[r["record"]].append(r["value"])
            if r["prop"] in NAMES and r.get("record"):
                self.named.setdefault(r["record"], r["value"])
        self.review = resources.read_jsonl(root / layout.IDENTICAL_JSONL) + [
            r for r in resources.read_jsonl(root / layout.LEDGER_JSONL) if r.get("rel") == "contradiction"]
        self.decided = set(vd.load(root)[0])

    def doc(self, ref: str) -> str:
        """A page or document id -> "<document title> p.<n>" / "<title>"."""
        ent = self.entity_of.get(ref, ref)
        p = self.props.get(ent) or {}
        title = lambda e: next(((self.props.get(e) or {}).get(k) or [None])[0] for k in DOC_TITLE
                               if (self.props.get(e) or {}).get(k)) if self.props.get(e) else None
        if p.get("document"):
            d = p["document"][0]
            return f"{title(self.entity_of.get(d, d)) or d} p.{(p.get('index') or ['?'])[0]}"
        return title(ent) or ref

    def documented(self, eid: str) -> list[str]:
        """Documents and pages linked to the entity as a whole."""
        return list(dict.fromkeys(self.doc(x["id"]) for x in (self.nodes.get(eid) or {}).get("linked") or []
                                  if schema.is_a(x.get("schema", ""), "Document") or x.get("schema") in ("Page", "Pages")))

    def sources(self, pairs) -> list[dict]:
        return [{"collection": c, "record": rec, "evidence": [self.doc(x) for x in self.cited.get(rec, [])]}
                for c, rec in sorted(pairs)]

    def involved(self, eid: str, prop: str, value: str) -> list[dict]:
        """The review rows this entity's `prop` = `value` took part in."""
        mine = {eid, *((self.nodes.get(eid) or {}).get("referents") or [])}
        n = self.norm(prop, value)
        cap = lambda rid: f'{rid} "{self.named[rid]}"' if rid in self.named else rid   # the record, as it names itself
        out = []
        for row in self.review:
            sides = [s for s in ("a", "b") if row.get(s) in mine]
            if not sides:
                continue
            decided = (row.get("of") or row["id"]) in self.decided
            for c in row.get("conflicts") or []:
                if c["prop"] != prop:
                    continue
                for s in sides:
                    other = "b" if s == "a" else "a"
                    if n in {self.norm(prop, x) for x in c[s]}:
                        out.append({"row": row["id"], "kind": row["rel"], "status": row["status"],
                                    "with": cap(row[other]), "with_id": row[other],
                                    "with_collection": self.collection_of.get(row[other], ""), "theirs": c[other],
                                    "decided": decided,
                                    "of": row.get("of")})
            for link in row.get("path") or []:          # a contradiction this value helped cause
                for sh in link.get("shared") or []:
                    for s in ("a", "b"):
                        if (link[s] in mine and sh[f"{s}_prop"] == prop and self.norm(prop, sh[s]) == n):
                            ends = sorted((link["a"], link["b"]))
                            out.append({"row": row["id"], "kind": "joined-despite-rejection",
                                        "status": row["status"], "via": link["id"],
                                        "this": cap(ends[0]), "with": cap(ends[1]),
                                        "this_id": ends[0], "with_id": ends[1],
                                        "decided": decided, "of": row.get("of")})
        # a contradiction already says what its rejected row says; one line per link
        superseded = {x["of"] for x in out if x["kind"] == "contradiction"}
        out = [x for x in out if not (x["kind"] == "sameAs" and x["row"] in superseded)]
        return list({(x["row"], x.get("via"), x.get("with")): x for x in out}.values())


def match(nodes: dict, text: str, kinds=(), exact: bool = False, fields: bool = True,
          free_text: bool = True) -> list[str]:
    """Node ids for the search `text`, best first: an id or a merged-in id, then an
    equal name, then names holding all its words (fewest extra words first), then
    names with a word starting each of its words (3 letters or more), then
    any other field holding them (with `exact`: equal to it; `fields=False`: not
    searched). Link fields are never searched: they name other records."""
    kinds = [kinds] if isinstance(kinds, str) and kinds else list(kinds or [])
    qn, qw = types.name_key(text)
    hits = []
    for rid, n in nodes.items():
        if not query.of_type(n.get("schema", ""), kinds):
            continue
        if text == rid or text in (n.get("referents") or []):
            hits.append((0, 0, rid))
            continue
        best = None
        for p in NAMES:
            for v in (n.get("props") or {}).get(p) or []:
                vn, vw = types.name_key(v)
                if vn and vn == qn:
                    best = (1, 0)
                elif not exact and qw and qw <= vw and (best is None or best > (2, len(vw - qw))):
                    best = best if best and best[0] == 1 else (2, len(vw - qw))
                elif (not exact and qw and all(len(q) >= 3 and any(w.startswith(q) for w in vw) for q in qw)
                      and (best is None or best > (2.5, len(vw)))):
                    best = (2.5, len(vw))                 # "gus" starts "gustavo": a name, after whole words
        if not best and fields:
            props, sname = n.get("props") or {}, n.get("schema", "")
            hit = (next(((p, v) for p in query.text_fields(props, sname, NAMES, free_text) for v in props[p]
                         if isinstance(v, str) and types.name_key(v)[0] == qn), None) if exact
                   else query.field_hit(props, text, skip=NAMES, schema_name=sname, free_text=free_text))
            if hit:
                best = (3, 0)
        if best:
            hits.append((*best, rid))
    return [rid for *_, rid in sorted(hits, key=lambda h: (h[0], h[1], h[2]))]


def same_value(ptypes: dict):
    """The comparison a disagreement uses: identifiers by their own normalizer,
    everything else by norm_text (case, accents and punctuation ignored), so
    "NORDWIND HOLDING AG" and "Nordwind Holding AG" are not a disagreement."""
    def norm(prop: str, v: str) -> str:
        t = ptypes.get(prop)
        return types.NORMALIZERS[t](v) if t in types.EXACT_TYPES else types.norm_text(v)
    return norm


def best_spelling(spellings: dict[str, set]) -> str:
    """Of several spellings the matcher treats as one value, the one to show:
    mixed case over all capitals or all lower case, accented over plain, then
    the one most collections wrote, then the longer (formatting kept:
    "CHE-101.202.303" over "CHE101202303"), then the first seen."""
    def score(item):
        v, colls = item
        letters = [c for c in v if c.isalpha()]
        mixed = bool(letters) and not (v.upper() == v or v.lower() == v)
        accented = any(ord(c) > 127 for c in letters)
        return (mixed, accented, len(colls), len(v))
    return max(spellings.items(), key=score)[0]


def grouped(rows: list[dict], eid: str, prop: str = "", collection: str = "", ptypes=None,
            distinct: set | None = None, trails: "Trails | None" = None) -> dict:
    """One entity's claims: {prop: [{value, also, collections}]}, where spellings
    the matcher treats as the same value are one line (`value` the best-formed,
    `also` the rest); plus `disputed`, the distinct-category properties (birth
    dates, id numbers...) whose collections give different values. Display only:
    the stored values are untouched."""
    norm = same_value(ptypes or {})
    by: dict[str, dict[str, dict[str, set]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    recs: dict[tuple, set] = defaultdict(set)             # (prop, normalized value) -> {(collection, record)}
    per_coll: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        if r["entity"] != eid or (prop and r["prop"] != prop) or (collection and r["collection"] != collection):
            continue
        n = norm(r["prop"], r["value"])
        by[r["prop"]][n][r["value"]].add(r["collection"])
        recs[(r["prop"], n)].add((r["collection"], r.get("record") or ""))
        per_coll[r["prop"]][r["collection"]].add(n)
    props = {}
    for p, groups in by.items():
        props[p] = []
        for n, spellings in groups.items():
            shown = best_spelling(spellings)
            entry = {"value": shown, "also": [v for v in spellings if v != shown],
                     "collections": sorted(set().union(*spellings.values()))}
            if trails:
                entry["sources"] = trails.sources(recs[(p, n)])
                entry["review"] = [x for v in spellings for x in trails.involved(eid, p, v)][:20]
                entry["review"] = list({json.dumps(x, sort_keys=True): x for x in entry["review"]}.values())
            props[p].append(entry)
    disputed = sorted(p for p, cv in per_coll.items()
                      if (distinct is None or p in distinct)
                      and len(cv) > 1 and len({frozenset(v) for v in cv.values()}) > 1)
    out = {"props": props, "disputed": disputed}
    if trails:
        out["documented_in"] = trails.documented(eid)
    return out


STATUS = {"rejected": "rejected", "confirmed": "confirmed", "proposed": "open", "conflict": "refused",
          "confirmed-stale": "stale", "auto": "auto"}


def _trail_rows(v: dict) -> list[list[tuple[str, str]]]:
    """Under a value, each review row it took part in, in the value table's
    columns: [value, record, collection, then the row and its status]. A
    contradiction adds the pair you rejected; a link in the chain that merged
    it (!) its two ends."""
    out = []
    for r in v.get("review") or []:
        if r["kind"] == "joined-despite-rejection":
            out.append([("! " + r["this_id"], "note"), (r["with_id"], ""), ("", ""),
                        (r["via"], "aside"), ("joined", "note"), ("rejected", "aside"), (r["of"], "aside")])
        elif r["kind"] == "contradiction":
            out.append([("≠ " + "; ".join(r["theirs"]), "note"), (r["with_id"], ""),
                        (r.get("with_collection", ""), "aside"), (r["row"], "aside"), ("merged", "note"),
                        ("rejected", "aside"), (r["of"], "aside")])
        else:
            out.append([("≠ " + "; ".join(r["theirs"]), "note"), (r["with_id"], ""),
                        (r.get("with_collection", ""), "aside"), (r["row"], "aside"),
                        (STATUS.get(r["status"], r["status"]), "note")] + ([("yours", "aside")] if r["decided"] else []))
    return out


SHOWN_VALUE = 60                                  # a longer value is cut, with …


def render_entity(n: dict, eid: str, g: dict) -> str:
    """One entity: a header row (name, type, id, claims, collections), then a
    table of its values, each on the line of the record that gave it, another
    spelling of it (=) and every review row it took part in under it; then the
    ids merged upstream and the documents linked to it."""
    total = sum(len(v["collections"]) for vals in g["props"].values() for v in vals)
    colls = {c for vals in g["props"].values() for v in vals for c in v["collections"]}
    cut = lambda s: s if len(s) <= SHOWN_VALUE else s[:SHOWN_VALUE - 1] + "…"
    head = ["entity", "type", "id", "claims", "collections"]
    top = [str(n.get("caption") or eid), str(n.get("schema") or ""), eid, str(total), str(len(colls))]
    hw = [max(len(a), len(b)) for a, b in zip(head, top)]
    cell = lambda x, i: f"{x:>{hw[i]}}" if i >= 3 else f"{x:<{hw[i]}}"
    out = [style.aside("   ".join(cell(x, i) for i, x in enumerate(head))),
           style.styled([(cell(x, i) + ("   " if i < 4 else ""), k) for i, (x, k)
                         in enumerate(zip(top, ("name", "aside", "aside", "", "")))]), ""]
    rows = []                                     # [mark, field, value parts, record, collection, extra parts]
    for p, vals in g["props"].items():
        mark = "≠" if p in g["disputed"] else " "
        first = True
        for v in vals:
            srcs = v.get("sources") or [{"record": "", "collection": c} for c in v["collections"]]
            for j, s in enumerate(srcs):
                rows.append([mark if first else " ", p if first else "", (cut(v["value"]) if j == 0 else "", ""),
                             s.get("record") or "", s.get("collection") or "", []])
                first = False
            for other in v.get("also") or []:     # the same value, spelled another way
                rows.append([" ", "", ("= " + cut(other), "aside"), "", "", []])
            for tr in _trail_rows(v):
                rows.append([" ", "", tr[0], tr[1][0], tr[2][0], tr[3:]])
    fw = max([len(r[1]) for r in rows] + [len("field")])
    vw = max([len(r[2][0]) for r in rows] + [len("value")])
    rw = max([len(r[3]) for r in rows] + [len("record")])
    cw = max([len(r[4]) for r in rows] + [len("collection")])
    out.append(style.aside(f"    {'field':<{fw}}   {'value':<{vw}}   {'record':<{rw}}   {'collection':<{cw}}".rstrip()))
    for mark, field, (value, vkind), rec, coll, extra in rows:
        parts = [("  ", ""), (mark + " ", "note"), (f"{field:<{fw}}", "accent"), ("   ", ""), (f"{value:<{vw}}", vkind),
                 ("   ", ""), (f"{rec:<{rw}}", "aside"), ("   ", ""), (f"{coll:<{cw}}", "aside")]
        for x in extra:
            parts += [("   ", ""), x]
        out.append(style.styled(parts).rstrip())
    upstream = sorted(set(n.get("referents") or ()) - {eid} - {s.get("record") for vals in g["props"].values()
                                                               for v in vals for s in v.get("sources") or []})
    if upstream or g.get("documented_in"):
        out.append("")
    for i, x in enumerate(upstream):              # merged before it reached this archive (FtM `referents`)
        out.append(style.aside(f"  {'merged upstream' if i == 0 else '':<15}   ") + x)
    for i, x in enumerate(g.get("documented_in") or []):
        out.append(style.aside(f"  {'documented in' if i == 0 else '':<15}   ") + x)
    return "\n".join(out)


def summarize(rows: list[dict], ptypes: dict | None = None, distinct_of=None) -> dict:
    norm = same_value(ptypes or {})
    by_coll, by_schema, by_prop = Counter(), Counter(), Counter()
    values: dict[tuple, dict] = defaultdict(lambda: defaultdict(set))  # (entity, prop) -> coll -> normalized
    raw: dict[tuple, dict] = defaultdict(lambda: defaultdict(set))     # the same, as the sources wrote it
    for r in rows:
        c = r.get("collection", "")
        by_coll[c] += 1
        by_schema[r.get("schema", "")] += 1
        by_prop[r.get("prop", "")] += 1
        n = norm(r["prop"], r["value"])
        values[(r["entity"], r["prop"])][c].add(n)
        raw[(r["entity"], r["prop"])][c].add(r["value"])
    schema_of = {r["entity"]: r.get("schema", "") for r in rows}
    disputed = [{"entity": e, "prop": p, "by_collection": {c: sorted(v) for c, v in sorted(raw[(e, p)].items())}}
                for (e, p), cv in sorted(values.items())
                if (distinct_of is None or p in distinct_of(schema_of.get(e, "")))
                and len(cv) > 1 and len({frozenset(v) for v in cv.values()}) > 1]
    return {"claims": len(rows), "entities": len({r["entity"] for r in rows}),
            "collections": dict(by_coll.most_common()), "schemas": dict(by_schema.most_common()),
            "props": dict(by_prop.most_common(10)),
            "disputed": len(disputed), "disputed_examples": disputed[:10]}


SCHEMAS_SHOWN = 10


def _cols(header: list[str], rows: list[list]) -> list[str]:
    """A table, plain text: the first column left, numbers right, `   ` between."""
    cells = [header] + [[str(x) for x in r] for r in rows]
    w = [max(len(c[i]) for c in cells) for i in range(len(header))]
    return [f"{c[0]:<{w[0]}}" + "".join(f"   {x:>{w[i + 1]}}" for i, x in enumerate(c[1:])) for c in cells]


def render(s: dict, name: str = "", width: int | None = None) -> str:
    """The totals, then claims by collection, by schema and by property side by
    side (one under another when the terminal is narrow), then the disputes."""
    import shutil
    totals = [("claims", s["claims"]), ("entities", s["entities"]), ("collections", len(s["collections"])),
              ("disputed", s["disputed"])]
    kw = max(len(k) for k, _ in totals)
    nw = max(len(f"{n:,}") for _, n in totals)
    out = [style.name("claims summary") + (f"   {name}" if name else ""), ""]
    out += [style.aside(f"  {k:<{kw}}") + f"   {n:>{nw},}" for k, n in totals]
    sch = list(s["schemas"].items())
    rest = sch[SCHEMAS_SHOWN:]
    tables = [_cols(["collection", "claims"], [list(x) for x in s["collections"].items()]),
              _cols(["schema", "claims"], [list(x) for x in sch[:SCHEMAS_SHOWN]]
                    + ([[f"{len(rest)} more", sum(n for _, n in rest)]] if rest else [])),
              _cols(["property", "claims"], [list(x) for x in s["props"].items()])]
    gap = "      "
    widths = [len(tb[0]) for tb in tables]
    out.append("")
    if sum(widths) + len(gap) * 2 + 2 <= (width or shutil.get_terminal_size((120, 24)).columns):
        for i in range(max(len(tb) for tb in tables)):
            cells = [tb[i] if i < len(tb) else "" for tb in tables]
            line = "  " + gap.join(f"{c:<{w}}" for c, w in zip(cells, widths))
            out.append((style.aside(line) if i == 0 else line).rstrip())
    else:
        for tb in tables:
            out += [style.aside("  " + tb[0])] + ["  " + x for x in tb[1:]] + [""]
    if s["disputed_examples"]:
        rows = [[d["entity"] if j == 0 else "", d["prop"] if j == 0 else "", c, v]
                for d in s["disputed_examples"] for j, (c, vals) in enumerate(d["by_collection"].items())
                for v in vals]
        ew, pw, cw = (max([len(r[i]) for r in rows] + [len(h)]) for i, h in enumerate(("entity", "field", "collection")))
        out += ["", style.aside(f"  {'entity':<{ew}}   {'field':<{pw}}   {'collection':<{cw}}   value")]
        out += [f"  {e:<{ew}}   " + style.accent(f"{p:<{pw}}") + f"   {c:<{cw}}   " + style.note(v)
                for e, p, c, v in rows]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    summary = bool(args) and args[0] == "summary"
    ap = argparse.ArgumentParser(prog="hydra-ctl claims",
                                 description="Where each value of an entity came from. Words that name a type "
                                             "(person, Company, ...) keep that type; the rest is searched for in "
                                             "names, then in every other field. No search: the overview.")
    ap.add_argument("words", nargs="*", metavar="[dir] [type] [search]",
                    help="an archive (optional), then types and search words, in any order")
    ap.add_argument("--type", default="", help="this FtM schema and its subtypes, any capitalisation")
    ap.add_argument("--prop", default="", help="only this property")
    ap.add_argument("--collection", default="", help="only claims from this collection")
    ap.add_argument("--exact", action="store_true", help="a name or value must equal the search, not just contain it")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    query.add_search_flags(ap)
    a = ap.parse_intermixed_args(args[1:] if summary else args)
    words = list(a.words)
    lead = words.pop(0) if words and resources.names_archive(words[0]) else None
    root = resources.ensure_built(resources.archive(lead, read_only=True))
    schema.load(root=root)
    words, with_sources = sources_mod.take_word(words)        # `claims gus sources`
    kinds, text = query.split(words, a.type)
    distinct = lru_cache(maxsize=None)(lambda sch: frozenset(_distinct(root, sch)))   # once per schema
    if summary or not text:                       # no search: the overview (of those types)
        rows = [r for r in load(root) if query.of_type(r.get("schema", ""), kinds)]
        s = summarize(rows, _prop_types(root), distinct)
        name = (resources.yamlcache.load(root / layout.MANIFEST) or {}).get("name") or root.name
        if with_sources:
            ids = sorted(n for n, v in resources.declared_nodes(root).items() if query.of_type(v.get("schema", ""), kinds))
            extra = sources_mod.show_for(root, ids, a.format) if a.format == "json" else None
            if a.format == "json":
                print(json.dumps({"summary": s, "sources": extra}, indent=1, ensure_ascii=False))
                return 0
            sys.stdout.write(render(s, name))
            sources_mod.show_for(root, ids)
            return 0
        sys.stdout.write(render(s, name) if a.format == "text" else json.dumps(s, indent=1, ensure_ascii=False) + "\n")
        return 0
    rows, nodes = load(root), resources.declared_nodes(root)
    mode = query.search_mode(root, a)
    ids = match(nodes, text, kinds, a.exact, fields=mode != "names", free_text=mode == "all")
    ptypes = _prop_types(root)
    trails = Trails(root, rows, nodes, ptypes)
    blocks = [(rid, grouped(rows, rid, a.prop, a.collection, ptypes, distinct(nodes[rid].get("schema")),
                            trails)) for rid in ids]
    if a.format == "json":
        found = [{"id": rid, "caption": nodes[rid].get("caption"), "schema": nodes[rid].get("schema"),
                  "referents": nodes[rid].get("referents") or [], **g} for rid, g in blocks]
        print(json.dumps({"entities": found, "sources": sources_mod.show_for(root, ids, "json")} if with_sources
                         else found, indent=1, ensure_ascii=False))
        return 0
    if not blocks:
        print("no entity matches" + (" (try without --exact)" if a.exact else ""))
    for rid, g in blocks[:SHOWN]:
        print(render_entity(nodes[rid], rid, g) + "\n")
    if len(blocks) > SHOWN:
        print(f"+{len(blocks) - SHOWN} more: narrow with a type, more words or --exact")
    if with_sources and ids:                      # every match, not just the ones shown
        sources_mod.show_for(root, ids)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
