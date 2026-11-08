from __future__ import annotations

import html
import json
from collections import defaultdict
from urllib.parse import unquote, urlsplit

from hydra import provenance, schema
from hydra.wiki import assets


def safe_url(value):
    try:
        parts = urlsplit(str(value or ""))
        return str(value) if parts.scheme.lower() in ("http", "https") and parts.hostname and not parts.username and not parts.password else ""
    except ValueError:
        return ""


def catalog(wiki):
    documents, entries = {}, {}
    by_url = defaultdict(list)
    for body, page in wiki.pages.items():
        if schema.is_a(page["schema"], "Document") or page["schema"] in ("Article", "Page", "Pages"):
            url = safe_url(wiki.first(body, "sourceUrl"))
            if url and body not in by_url[url]:
                by_url[url].append(body)

    def saved(body, title):
        key = "document:" + body
        if key not in documents:
            page = wiki.pages.get(body)
            first = lambda prop: str(wiki.first(body, prop) or "") if page else ""
            url = safe_url(first("sourceUrl"))
            publisher_url = safe_url(first("publisherUrl"))
            documents[key] = {
                "id": key, "title": page["title"] if page else title or "Unresolved document",
                "body": body if page else "", "url": url,
                "group": provenance.origin(url or publisher_url) if url or publisher_url else first("publisher") or "Kept documents",
                "publisher": first("publisher"), "published": first("publishedAt") or first("publicationDate"),
                "retrieved": first("retrievedAt"), "kind": "saved" if page else "unresolved",
                "entries": set(), "records": {}, "notes": {},
            }
        return key

    def linked(raw):
        url = safe_url(raw)
        if url and len(by_url.get(url, [])) == 1:
            body = by_url[url][0]
            return saved(body, wiki.pages[body]["title"])
        key = "url:" + str(raw)
        if key not in documents:
            parts = urlsplit(url) if url else None
            title = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1]).replace("_", " ").replace("-", " ") if parts else str(raw)
            documents[key] = {
                "id": key, "title": title or provenance.origin(url), "body": "", "url": url,
                "group": provenance.origin(url) if url else "Other references", "publisher": "",
                "published": "", "retrieved": "", "kind": "link",
                "entries": set(), "records": {}, "notes": {},
            }
        return key

    for body in sorted(wiki.listed):
        page = wiki.pages[body]
        cited, missing, wikipedia = set(), set(), set()
        for n, citation in enumerate(page.get("citations") or []):
            record = json.dumps([citation.get("member"), citation.get("record") or [body, n]], ensure_ascii=True)
            origins = provenance._origins(citation, wiki.pages)
            if origins == ["unsourced"]:
                missing.add(record)
            else:
                cited.add(record)
                if all(provenance.is_wiki(o) for o in origins):
                    wikipedia.add(record)
            ids = {saved(d["h"], d.get("title")) for d in citation.get("docs") or [] if d.get("h")}
            for d in citation.get("docs") or []:
                if not d.get("h"):
                    key = "unresolved:" + str(d.get("title") or "Unknown document")
                    if key not in documents:
                        documents[key] = {
                            "id": key, "title": d.get("title") or "Unknown document", "body": "", "url": "",
                            "group": "Unresolved references", "publisher": "", "published": "", "retrieved": "",
                            "kind": "unresolved", "entries": set(), "records": {}, "notes": {},
                        }
                    ids.add(key)
            ids.update(linked(url) for url in citation.get("urls") or [])
            for key in ids:
                doc = documents[key]
                doc["entries"].add(body)
                doc["records"].setdefault(record, set()).add(body)
                if citation.get("quote"):
                    doc["notes"][record] = citation["quote"]
        entries[body] = {
            "id": body, "title": page["title"], "missing": len(missing),
            "coverage": "wiki" if cited and cited == wikipedia else "other" if cited else "none",
        }
    for doc in documents.values():
        doc["entries"] = sorted(doc["entries"], key=lambda b: entries[b]["title"].casefold())
        doc["records"] = [{"id": record, "entries": sorted(bodies)} for record, bodies in sorted(doc["records"].items())]
        doc["notes"] = list(dict.fromkeys(doc["notes"].values()))
    return {"documents": list(documents.values()), "entries": list(entries.values())}


def render(wiki, links):
    data = wiki.source_catalog
    data = {
        "documents": [{**d, "href": links.page(d["body"]) if d["body"] else ""} for d in data["documents"]],
        "entries": [{**entry, "href": links.page(entry["id"])} for entry in data["entries"]],
    }
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    filters = "".join(f"<button type=button data-source-filter='{key}' aria-pressed={'true' if key == 'all' else 'false'}>{html.escape(label)}</button>"
                      for key, label in (("all", "All sources"), ("saved", "Saved records"), ("wiki", "Wikipedia-only"), ("missing", "Missing sources")))
    return ("<section class=source-browser id=source-browser aria-label='Source browser'>"
            "<div class=source-controls><label for=source-search>Find evidence</label>"
            "<input id=source-search type=search placeholder='Publisher, source title or entry' autocomplete=off>"
            f"<div class=seg role=group aria-label='Source filters'>{filters}</div></div>"
            "<div class=source-workspace><section class='panel source-index' aria-label='Publishers and websites'>"
            "<h2>Publishers / websites</h2><p class=meta id=source-summary aria-live=polite></p>"
            "<div id=source-groups></div><div id=source-group-pages class=source-pagination></div></section>"
            "<section class='panel source-inspector' aria-label='Selected source' id=source-inspector></section></div>"
            "<noscript><p>Enable JavaScript to browse sources. Coverage by collection remains available below.</p></noscript>"
            f"<script type=application/json id=source-data>{payload}</script>"
            f"<script>{assets.script('sources.js')}</script></section>")
