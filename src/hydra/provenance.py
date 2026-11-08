"""provenance.py — where an archive's facts come from, and how much rests on Wikipedia (the W-factor).

Every value on a page carries footnotes; every footnote is a record, which cites URLs or kept
documents. This counts those citations by origin (the site a URL belongs to, or the publisher of a
kept document) for the whole archive, each collection, each entry and each property, and gives the
W-factor: of the citations that cite anything, the share that rest on Wikipedia alone. A citation
that also cites another origin does not count as Wikipedia-only; one that cites nothing is counted
apart (`unsourced`).

It also ranks the entries whose facts rest most on Wikipedia, with the records to re-source, so an
agent or a person can replace each citation with the source Wikipedia itself cites (hydra-mcp
`wikipedia_footnotes` finds it, `swap_source` makes the change once the new source's own words are
quoted). Context entries (scope.yaml) are not counted.

    report(root, top=25) -> {w, citations, origins, collections, entries: [...], suggestions: [...]}
    origin(url) -> "wikipedia.org", "reuters.com", ...
"""
from __future__ import annotations

import urllib.parse
from collections import Counter, defaultdict

from hydra.universe import layer

WIKI = ("wikipedia.org", "wikimedia.org", "wikidata.org")


def origin(url: str) -> str:
    host = urllib.parse.urlsplit(str(url or "")).netloc.lower().split("@")[-1].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    parts = host.split(".")
    for w in WIKI:                                   # en.wikipedia.org, de.m.wikipedia.org -> wikipedia.org
        if host == w or host.endswith("." + w):
            return w
    return ".".join(parts[-3:]) if len(parts) > 2 and len(parts[-2]) <= 3 else ".".join(parts[-2:]) or "unknown"


def is_wiki(o: str) -> bool:
    return o in WIKI


def _origins(c: dict, pages: dict) -> list[str]:
    """A citation's origins: its URLs' sites, else its kept documents' URLs or publishers."""
    out = [origin(u) for u in c.get("urls") or []]
    for d in c.get("docs") or ():
        doc = pages.get(d.get("h")) if d.get("h") else None
        vals = [v.get("value") for b in (doc or {}).get("infobox") or [] if b["prop"] in ("sourceUrl", "publisherUrl")
                for v in b["values"] if v.get("value")]
        pub = [v.get("value") for b in (doc or {}).get("infobox") or [] if b["prop"] == "publisher"
               for v in b["values"] if v.get("value")]
        out += [origin(u) for u in vals] or [str(p).lower() for p in pub] or ([] if out else ["kept document"])
    return list(dict.fromkeys(out)) or ["unsourced"]


def report(root, top: int = 25) -> dict:
    pages = {p["body"]: p for p in layer.read_parsed(root, "pages.jsonl", missing=[])}
    listed = [p for p in pages.values() if (p.get("scope") or {}).get("in", True)]
    origins, by_coll = Counter(), defaultdict(lambda: [0, 0, 0])      # per collection: sourced, Wikipedia-only, unsourced
    seen_rec, total, wiki_only, unsourced = set(), 0, 0, 0
    entries = []
    for p in listed:
        n_cit = n_wiki = 0
        recs = []
        for c in p["citations"]:
            o = _origins(c, pages)
            key = (c.get("member"), c.get("record"))
            first = key not in seen_rec                # the archive's totals count each record once
            seen_rec.add(key)
            if o == ["unsourced"]:                   # cites nothing: counted apart, not in the W-factor
                unsourced += first
                if first:
                    origins.update(o)
                    by_coll[c.get("collection") or "?"][2] += 1
                continue
            only = all(is_wiki(x) for x in o)
            n_cit += 1
            n_wiki += only
            if first:
                total += 1
                wiki_only += only
                origins.update(o)
                col = c.get("collection") or "?"
                by_coll[col][0] += 1
                by_coll[col][1] += only
            if only:
                recs.append({"record": c.get("record"), "collection": c.get("collection"),
                             "url": next(iter(c.get("urls") or []), None), "quote": c.get("quote") or ""})
        props = {}
        for b in p["infobox"]:
            cites = [n for v in b["values"] for n in v.get("cites") or []
                     if _origins(p["citations"][n - 1], pages) != ["unsourced"]]
            if cites:
                wn = sum(1 for n in cites if all(is_wiki(x) for x in _origins(p["citations"][n - 1], pages)))
                props[b["prop"]] = round(wn / len(cites), 2)
        if n_cit:
            entries.append({"title": p["title"], "h": p["h"], "body": p["body"], "schema": p["schema"],
                            "citations": n_cit, "wikipedia_only": n_wiki, "w": round(n_wiki / n_cit, 2),
                            "properties": props, "records": recs})
    entries.sort(key=lambda x: (-x["wikipedia_only"], -x["w"], x["title"]))
    sugg = [x for x in entries if x["wikipedia_only"]][:top]
    return {"w": round(wiki_only / total, 3) if total else 0.0, "citations": total, "wikipedia_only": wiki_only,
            "unsourced": unsourced,
            "origins": origins.most_common(), "entries_counted": len(entries),
            "entries_wikipedia_only": sum(1 for x in entries if x["w"] == 1.0),
            "collections": sorted(({"collection": k, "citations": v[0], "wikipedia_only": v[1], "unsourced": v[2],
                                    "w": round(v[1] / v[0], 2) if v[0] else 0.0} for k, v in by_coll.items()),
                                  key=lambda x: (-x["w"], -x["citations"])),
            "suggestions": sugg}
