"""sources.py — the sources an archive's entities cite.

    hydra-ctl sources [<dir>] [type] [search] [--uncited] [--names|--no-text]
        [--format text|json] [--ascii]

A tree per source, the source at the top: each source entry
(`.hydra/sources/entries/`: the Articles and documents the data comes from)
with its type, publisher, id and link, and under it the entities that cite it,
each with the field that cites (`sources`) and, when the entity was merged from
other records, which of its records does. A document's pages sit under it, and
the entities citing a page under that page. Documents that are part of the data
itself (a case file and its pages in a collection) are listed apart, since they
are content, not where the content came from. Entities citing nothing are
counted; `--uncited` names them.

A type word (`sources person`) keeps to what entities of that type cite; a
search (`sources hank`) to what the entities it names cite (names first, other
fields only when no name matches): only those sources, and only those entities
under them. When no entity matches, the search is tried on the sources
themselves (id, title, publisher, link): `sources casefile` lists those sources
with everything citing them.

The word `sources` at the end of `claims`, `node find` or `tree` does the same
for just the entities that command returned:

    hydra-ctl claims gus sources
    hydra-ctl node find walt sources
    hydra-ctl tree organization sources

Read from the last build (`.hydra/parsed/claims.jsonl` and the declared read);
never builds."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from hydra import layout, query, resources, schema
from hydra.cli import style

WORD = "sources"                                  # the trailing word other commands take
DOC_TITLE = ("title", "name", "fileName")


def is_document(schema_name: str) -> bool:
    return schema.is_a(schema_name or "", "Document") or schema_name in ("Page", "Pages")


def take_word(words: list[str]) -> tuple[list[str], bool]:
    """(the words without `sources`, whether it was there)."""
    kept = [w for w in words if w.lower() != WORD]
    return kept, len(kept) != len(words)


def catalog(root) -> dict[str, dict]:
    """{document id: {id, schema, title, publisher, url, collection, entry,
    document, page}} for every document and page in the build; `entry` is True
    for one in .hydra/sources/entries/; a page carries its `document` and `page`
    (its index), and its title is "<document title> p.<n>"."""
    props: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    meta: dict[str, tuple] = {}
    for r in resources.read_jsonl(Path(root) / layout.CLAIMS_JSONL):
        props[r["entity"]][r["prop"]].append(r["value"])
        meta.setdefault(r["entity"], (r.get("schema") or "", r.get("collection") or ""))
    first = lambda e, k: ((props.get(e) or {}).get(k) or [""])[0]
    title = lambda e: next((first(e, k) for k in DOC_TITLE if first(e, k)), "")
    out = {}
    for e, (sname, coll) in meta.items():
        if not is_document(sname):
            continue
        t, d = title(e), first(e, "document")
        if d:                                         # a page: "<document title> p.<n>"
            t = f"{title(d) or d} p.{first(e, 'index') or '?'}"
        out[e] = {"id": e, "schema": sname, "title": t or e, "publisher": first(e, "publisher"),
                  "url": first(e, "sourceUrl"), "collection": coll, "entry": coll.startswith(layout.SOURCE_COLLECTION),
                  "document": d, "page": first(e, "index") if d else ""}
    titled = defaultdict(list)                        # a page may name its document by title, not id
    for e, x in out.items():
        if not x["document"]:
            titled[x["title"]].append(e)
    for x in out.values():
        d = x["document"]
        if d and d not in out and len(titled.get(d) or []) == 1:
            x["document"] = titled[d][0]
    return out


def find(root, text: str) -> list[str]:
    """The sources whose id, title, publisher or link contain `text`, any case."""
    t = text.lower()
    return [d for d, s in catalog(root).items()
            if any(t in str(s.get(k) or "").lower() for k in ("id", "title", "publisher", "url"))]


def report(root, entity_ids=None, source_ids=None) -> dict:
    """What `entity_ids` (default: every entity) cite: {matched, entities,
    entries: [...], documents: [...], unsourced: [...]}. Each source carries
    `cited_by` [{id, caption, schema, records}] (`records`: the records whose
    `sources` field names it), and a document its cited `pages` (each a source
    the same way). With `entity_ids`, only the sources they cite and only them
    under each; with `source_ids`, just those sources, with every entity citing
    them."""
    nodes, docs = resources.declared_nodes(root), catalog(root)
    via: dict[tuple, set] = defaultdict(set)          # (source, entity) -> the records citing it
    for r in resources.read_jsonl(Path(root) / layout.CLAIMS_JSONL):
        if r["prop"] == WORD and r.get("record") and r["value"] in docs:
            via[(r["value"], r["entity"])].add(r["record"])
    ids = [i for i in (entity_ids if entity_ids is not None else sorted(nodes)) if i in nodes]
    cites: dict[str, list] = defaultdict(list)
    unsourced = []
    for i in ids:
        cited = [d for d in dict.fromkeys((nodes[i].get("props") or {}).get(WORD) or []) if d in docs]
        for d in cited:
            cites[d].append(i)
        if not cited:
            unsourced.append(i)
    cap = lambda i: nodes[i].get("caption") or i
    if source_ids is not None:                        # the sources asked for: every entity citing them
        cites = defaultdict(list)
        for i in sorted(nodes):
            for d in dict.fromkeys((nodes[i].get("props") or {}).get(WORD) or []):
                if d in docs:
                    cites[d].append(i)
        shown = {d for d in source_ids if d in docs}
        unsourced = []
    else:
        shown = set(cites) | ({d for d in docs if docs[d]["entry"]} if entity_ids is None else set())
    shown |= {docs[d]["document"] for d in shown if docs[d]["document"] in docs}   # a page's document above it

    def row(d):
        return {**docs[d], "cited_by": [{"id": i, "caption": cap(i), "schema": nodes[i].get("schema") or "",
                                         "records": sorted(via.get((d, i)) or [])}
                                        for i in sorted(cites.get(d) or [], key=lambda i: (str(cap(i)).lower(), i))]}
    pages = defaultdict(list)
    for d in shown:
        if docs[d]["document"] in shown:
            pages[docs[d]["document"]].append(d)
    num = lambda d: (int(docs[d]["page"]) if str(docs[d]["page"]).isdigit() else 1 << 30, docs[d]["title"].lower(), d)
    tops = sorted((d for d in shown if docs[d]["document"] not in shown), key=lambda d: (docs[d]["title"].lower(), d))
    tree = lambda d: {**row(d), **({"pages": [row(p) for p in sorted(pages[d], key=num)]} if pages.get(d) else {})}
    entries = [tree(d) for d in tops if docs[d]["entry"]]
    documents = [tree(d) for d in tops if not docs[d]["entry"]]
    every = {c["id"] for s in entries + documents for x in [s] + (s.get("pages") or []) for c in x["cited_by"]}
    return {"matched": "entities" if source_ids is None else "sources",
            "entities": len(ids) if source_ids is None else len(every),
            "entries": entries, "documents": documents,
            "unsourced": [{"id": i, "caption": cap(i), "schema": nodes[i].get("schema") or ""}
                          for i in sorted(unsourced, key=lambda i: (str(cap(i)).lower(), i))]}


def _model(s: dict, page: bool = False) -> dict:
    """One source as a `tree` node: its title (just "p.<n>" for a page under its
    document), type, publisher and id; its link under it; its pages, then the
    entities citing it, as children. An entity's line names the field that
    cites (`sources`), and the records it came from when not the entity's own."""
    title = f"p.{s['page']}" if page and s.get("page") else s["title"]
    parts = [(title, "name"), (f" ({s['schema']})", "aside")]
    parts += [("   ", ""), (s["publisher"], "")] if s.get("publisher") else []
    parts += [("   ", ""), (s["id"], "aside")]
    kids = [_model(p, page=True) for p in s.get("pages") or []]
    for c in s["cited_by"]:
        recs = [r for r in c["records"] if r != c["id"]]
        kids.append({"name": c["caption"], "children": [], "_parts": [
            (str(c["caption"]), "name"), (f" ({c['schema']})", "aside"), ("   ", ""),
            (WORD + (" of " + ", ".join(recs) if recs else ""), "accent"), ("   ", ""), (c["id"], "aside")]})
    if not kids:
        kids = [{"name": "-", "children": [], "_parts": [("cited by none", "aside")]}]
    return {"name": title, "_parts": parts, "children": kids, "also": [s["url"]] if s.get("url") else []}


def render(rep: dict, scoped: bool = False, name: str = "", uncited: bool = False, ascii: bool = False) -> str:
    """A tree per source: the source entries first, then the documents found in
    the data, a blank line between sources; last, how many cite nothing (with
    `uncited`, each of them, as name, type, id)."""
    from hydra import tree
    lines = [style.name("sources") + (f"   {name}" if name and not scoped else "")]
    if scoped:
        lines += ["", style.aside("  entities") + f"   {rep['entities']}"]
    for heading, group in (("entries", rep["entries"]), ("documents", rep["documents"])):
        if not group:
            continue
        lines += ["", style.aside(f"  {heading}"), ""]
        model = [{**_model(s), "group": k} for k, s in enumerate(group)]
        lines += [("  " + x) if x else x for x in tree.render(model, ascii=ascii).rstrip("\n").split("\n")]
    if rep.get("matched") == "sources":           # sources searched for: nothing to count as uncited
        return "\n".join(lines) + "\n"
    lines += ["", style.aside(f"  {'uncited':<{8 if scoped else 7}}") + "   " + (style.note(str(len(rep["unsourced"])))
                                                     if rep["unsourced"] else "0")]
    if uncited and rep["unsourced"]:
        cw = max(len(str(c["caption"])) for c in rep["unsourced"])
        sw = max(len(c.get("schema") or "") for c in rep["unsourced"])
        for c in rep["unsourced"]:
            lines.append("     " + style.styled([(f"{str(c['caption']):<{cw}}", ""), ("   ", ""),
                                                 (f"{c.get('schema') or '':<{sw}}", "aside"), ("   ", ""),
                                                 (c["id"], "aside")]).rstrip())
    return "\n".join(lines) + "\n"


def show_for(root, ids, fmt: str = "text") -> dict | None:
    """The trailing `sources` of another command: printed (text), or returned to
    be put beside that command's JSON."""
    rep = report(root, list(dict.fromkeys(ids)))
    if fmt == "json":
        return rep
    sys.stdout.write("\n" + render(rep, scoped=True))
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl sources",
                                 description="The sources the archive's entities cite, and who cites each.")
    ap.add_argument("words", nargs="*", metavar="[dir] [type] [search]",
                    help="an archive (optional); a type (person, organization...) keeps to what entities of that "
                         "type cite; anything else searches the entities, then the sources themselves")
    ap.add_argument("--uncited", action="store_true", help="name each entity citing nothing, not just count them")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--ascii", action="store_true", help="|-- \\-- | instead of box-drawing")
    query.add_search_flags(ap)
    a = ap.parse_intermixed_args(argv)
    words = list(a.words)
    lead = words.pop(0) if words and resources.names_archive(words[0]) else None
    root = resources.ensure_built(resources.archive(lead, read_only=True))
    schema.load(root=root)
    kinds, text = query.split(words)
    scoped = bool(kinds or text)
    if text:
        from hydra.claims import match
        nodes, mode = resources.declared_nodes(root), query.search_mode(root, a)
        ids = match(nodes, text, kinds, fields=False) or (
            [] if mode == "names" else match(nodes, text, kinds, free_text=mode == "all"))
        docs = [] if ids or kinds else find(root, text)
        if not ids and not docs:
            print("no record or source matches")
            return 0
        rep = report(root, ids) if ids else report(root, source_ids=docs)
    elif kinds:
        rep = report(root, sorted(i for i, n in resources.declared_nodes(root).items() if query.of_type(n.get("schema", ""), kinds)))
    else:
        rep = report(root)
    if a.format == "json":
        sys.stdout.write(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
        return 0
    name = (resources.yamlcache.load(root / layout.MANIFEST) or {}).get("name") or root.name
    sys.stdout.write(render(rep, scoped=scoped, name=name, uncited=a.uncited, ascii=a.ascii))
    return 0
