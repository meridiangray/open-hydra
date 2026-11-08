"""scope.py — what an archive is about, and what is only context (.hydra/rules/scope.yaml).

An archive about a family also holds the people its sources mention in passing: a painting's
owners four centuries ago, the auction house, the other side of a deal. They stay in the data
(their ids, keys and merges are untouched) but they are context: the wiki names them as text
on the pages that mention them, gives them no listing, and `wiki check` does not count them.

Scope is computed, never tagged on records. It starts at the `seeds` and flows along the
relationships `flow` names, in the direction it names, and no further:

    seeds:   collections: [core]          every entity a seed collection records
             entities: [H-..., "wikidata:Q..."]
    flow:    edges: {Family: both, Ownership: owner, Membership: member, ...}
                 a relationship passes scope from the end named (or both ends) to the other:
                 `Ownership: owner` takes what an in-scope owner owns, never an asset's other owners
             properties: [organization]    an entity property passes scope to what it names (a post's body)
             deals: true                   an Event is in scope when an in-scope entity is involved in it,
                                           organizes it, or names it in a record's `transaction`
    include: [...]   always in scope (and scope flows on from them): an H, a key, a record id, a title,
                     or `collection:<name>`
    exclude: [...]   never in scope, and scope does not flow through them

The documents in-scope pages cite are in scope too (their references stay links).
No `seeds`: everything is in scope (the default; nothing changes for an archive without the file).

    load(root)                  -> the rules
    compute(pages, conf)        -> {body: why} for the bodies in scope ("seed: collection core",
                                   "Ownership from Cy Vale", ...); None when no seeds
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from hydra import layout, resources, yamlcache

DEFAULT_FLOW = {
    "edges": {"Family": "both", "Membership": "member", "Occupancy": "both", "Ownership": "owner",
              "Directorship": "director", "Employment": "employee", "Representation": "client"},
    "properties": ["organization"],
    "deals": True,
}


def path(root) -> Path:
    own = Path(root) / layout.SCOPE if root else None
    return own if own and yamlcache.is_file(own) else resources.TEMPLATE / layout.SCOPE


def load(root) -> dict:
    f = path(root)
    doc = yamlcache.load(f) if yamlcache.is_file(f) else None
    doc = doc if isinstance(doc, dict) else {}
    seeds = doc.get("seeds") or {}
    user_flow = doc.get("flow") if isinstance(doc.get("flow"), dict) else {}
    flow = {**DEFAULT_FLOW, **user_flow,
            "edges": {**DEFAULT_FLOW["edges"], **(user_flow.get("edges") or {})}
            if isinstance(user_flow.get("edges"), dict) else DEFAULT_FLOW["edges"]}
    return {"seeds": {"collections": [str(x) for x in seeds.get("collections") or []],
                      "entities": [str(x) for x in seeds.get("entities") or []]},
            "flow": flow, "include": [str(x) for x in doc.get("include") or []],
            "exclude": [str(x) for x in doc.get("exclude") or []], "file": str(f)}


def active(conf: dict) -> bool:
    s = conf["seeds"]
    return bool(s["collections"] or s["entities"] or conf["include"])


def _resolver(pages: list[dict]):
    """A reference (H, body, key, record id, title, `collection:<name>`) -> the bodies it names."""
    from hydra.universe import hid
    by_body = {p["body"]: p for p in pages}
    by_key, by_record, by_title, by_coll = defaultdict(set), defaultdict(set), defaultdict(set), defaultdict(set)
    for p in pages:
        for k in p.get("keys") or ():
            by_key[f"{k['ns']}:{k['key']}".casefold()].add(p["body"])
        for m in p.get("members") or ():
            by_record[m.split("/", 1)[-1]].add(p["body"])
            by_record[m].add(p["body"])
        by_title[p["title"].casefold()].add(p["body"])
        for c in p.get("citations") or ():
            if c.get("collection"):
                by_coll[c["collection"]].add(p["body"])

    def names(ref: str) -> set[str]:
        ref = ref.strip()
        if ref.startswith("collection:"):
            return set(by_coll.get(ref[len("collection:"):], ()))
        try:
            b = hid.body(ref)
            if b in by_body:
                return {b}
        except ValueError:
            pass
        return set(by_key.get(ref.casefold(), ())) or set(by_record.get(ref, ())) or set(by_title.get(ref.casefold(), ()))
    return names, by_coll


def compute(pages: list[dict], conf: dict, schemas: dict | None = None) -> dict | None:
    """{body: why} for every body in scope; None when the rules name no seeds (all in scope).
    `schemas`: {edge schema: (source prop, target prop)}, to read `flow.edges` ends by name."""
    if not active(conf):
        return None
    by_body = {p["body"]: p for p in pages}
    names, by_coll = _resolver(pages)
    excluded = set().union(*(names(x) for x in conf["exclude"])) if conf["exclude"] else set()
    why: dict[str, str] = {}

    def add(b, reason):
        if b in by_body and b not in why and b not in excluded:
            why[b] = reason
            return True
        return False

    for c in conf["seeds"]["collections"]:
        for b in by_coll.get(c, ()):
            add(b, f"seed: collection {c}")
    for ref in conf["seeds"]["entities"]:
        for b in names(ref):
            add(b, f"seed: {ref}")
    for ref in conf["include"]:
        for b in names(ref):
            add(b, f"included: {ref}")

    edges = conf["flow"].get("edges") or {}
    props = set(conf["flow"].get("properties") or ())
    ends = schemas or {}

    def passes(r) -> bool:
        rule = edges.get(r.get("edge"))
        if not rule:
            return False
        if rule == "both":
            return True
        src, tgt = ends.get(r.get("edge"), (None, None))
        return (rule == src and r.get("side") == "source") or (rule == tgt and r.get("side") == "target")

    title = lambda b: by_body[b]["title"]
    frontier = list(why)
    while frontier:
        nxt = []
        for b in frontier:
            p = by_body[b]
            for r in p["relations"]:
                o = r.get("other")
                if o and passes(r) and add(o, f"{r['edge']} from {title(b)}"):
                    nxt.append(o)
            for box in p["infobox"]:
                if box["prop"] in props:
                    for v in box["values"]:
                        if v.get("h") and add(v["h"], f"{box['label']} of {title(b)}"):
                            nxt.append(v["h"])
        if conf["flow"].get("deals") and not nxt:            # deals, once the rest has settled
            for p in pages:
                if p["schema"] != "Event" or p["body"] in why:
                    continue
                party = next((v["h"] for box in p["infobox"] if box["prop"] in ("involved", "organizer")
                              for v in box["values"] if v.get("h") in why), None)
                named = party or next((b for b in why for r in by_body[b]["relations"]
                                       if p["body"] in ((r.get("links") or {}).get("transaction") or [r.get("transaction")])),
                                      None)
                if named and add(p["body"], f"deal of {title(named)}"):
                    nxt.append(p["body"])
        frontier = nxt
    for b in list(why):                                    # the documents in-scope pages cite: their sources
        for c in by_body[b].get("citations") or ():
            for d in c.get("docs") or ():
                if d.get("h"):
                    add(d["h"], f"source of {title(b)}")
    return why
