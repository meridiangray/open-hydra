"""keys.py — the keys an entity is known by elsewhere (.hydra/rules/keys.yaml).

A record's `upstream` holds its canonical pins: an H (`H-p0-...`, or `label:H-...`), or a key
`namespace:key` that some system assigned it (`wikidata:Q57340`, `acme:EMP-0042`). Records
that carry one key are one entity, in one collection or across many; a person's "two
entities" still wins (the merge is blocked and reported). A record may carry as many keys
as it has sources.

Declaring a namespace is optional; an undeclared one still merges and `wiki check` lists it,
so a typo shows. A declared namespace may say:

    label     how a reader sees it ("Wikidata")
    url       a link for the key: "https://www.wikidata.org/wiki/{key}"
    property  the FtM property holding the same key (`wikidataId`): a value there is that key too
    unique    true: an entity holds at most one key here; two in one entity is a conflict
    case      upper | lower: how a key is written before it is compared (default: as written)

`primary:` (a namespace, or a list in order of preference) names the key an entity is keyed
by first: its H is derived from that key rather than from its first record, so the H holds
however the records change, and its page lists that key first.

    load(root)                 -> {"namespaces": {ns: {...}}, "primary": [ns, ...]}
    parse(value)               -> (ns, key) for a key, None for an H or no namespace
    norm(conf, ns, key)        -> the key as compared
    of_record(conf, props, defs) -> {"ns:key", ...}: a record's keys, from upstream and declared properties
"""
from __future__ import annotations

from pathlib import Path

from hydra import layout, resources, yamlcache


def path(root) -> Path:
    own = Path(root) / layout.KEYS if root else None
    return own if own and yamlcache.is_file(own) else resources.TEMPLATE / layout.KEYS


def load(root) -> dict:
    f = path(root)
    if not yamlcache.is_file(f):
        return {"namespaces": {}, "primary": []}
    doc = yamlcache.load(f) or {}
    doc = doc if isinstance(doc, dict) else {}
    prim = doc.get("primary") or []
    prim = [prim] if isinstance(prim, str) else list(prim)
    nss = {str(k).lower(): (v if isinstance(v, dict) else {}) for k, v in (doc.get("namespaces") or {}).items()}
    return {"namespaces": nss, "primary": [str(p).lower() for p in prim]}


def parse(value) -> tuple[str, str] | None:
    """`wikidata:Q57340` -> ("wikidata", "Q57340"). None for an H (`H-...`, `label:H-...`) or a
    value with no namespace."""
    from hydra.universe import hid
    text = str(value or "").strip()
    ns, sep, key = text.partition(":")
    if not sep or not ns.strip() or not key.strip() or hid.is_h(text):
        return None
    try:
        hid.split_pin(text)
        return None                      # `label:H-...`: an H of a named universe
    except ValueError:
        return ns.strip().lower(), key.strip()


def norm(conf: dict, ns: str, key: str) -> str:
    case = (conf["namespaces"].get(ns) or {}).get("case")
    key = key.strip()
    return key.upper() if case == "upper" else key.lower() if case == "lower" else key


def text(conf: dict, value) -> str | None:
    """A key value -> `ns:key` as compared, or None when it is no key."""
    p = parse(value)
    return f"{p[0]}:{norm(conf, *p)}" if p else None


def by_property(conf: dict) -> dict:
    """{FtM property: namespace} for the declared namespaces that name one."""
    return {v["property"]: ns for ns, v in conf["namespaces"].items() if v.get("property")}


def of_record(conf: dict, props: dict) -> set[str]:
    """Every key a record carries: its `upstream` keys, and the values of declared properties."""
    out = {k for v in props.get("upstream") or [] if (k := text(conf, v))}
    for prop, ns in by_property(conf).items():
        out.update(f"{ns}:{norm(conf, ns, str(v))}" for v in props.get(prop) or [] if str(v).strip())
    return out


def rank(conf: dict, ns: str) -> int:
    """Where a namespace stands in `primary` (lower is preferred); after all of them when not listed."""
    return conf["primary"].index(ns) if ns in conf["primary"] else len(conf["primary"])


def describe(conf: dict, k: str) -> dict:
    """`ns:key` -> what a page shows: {ns, key, label, url, declared, primary}."""
    ns, key = k.split(":", 1)
    d = conf["namespaces"].get(ns)
    url = (d or {}).get("url")
    return {"ns": ns, "key": key, "label": (d or {}).get("label") or ns, "declared": d is not None,
            "url": url.replace("{key}", key) if url else None, "primary": ns in conf["primary"]}
