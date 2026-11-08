"""declared.py — page sections defined in wiki.yaml, with no Python.

`define:` names a section; `sections:` (per schema) and `panel:` then use that name like any built-in one.

    define:
      vessels_owned:
        title: Vessels owned
        relations: {edge: ownership, side: source, other: Vessel}   # a page's relationships, filtered
        columns: [name, share, period, {label: Tonnage, prop: tonnage}]
        sort: [former, -share, name]
      specification:
        title: Specification
        props: [tonnage, flag, builtDate]                          # a table of this page's own properties
      voyages:
        title: Voyages
        relations: {edge: Voyage, side: source}
        view: timeline                                             # table (default) | list | timeline

relations   edge       a role (person, post, event, tenure, kin, ownership, representation: roles.py) or an edge name
            side       source | target       (which end this page is)
            verb       one verb, or a list
            other      a schema the other end is (or extends)
            former     false: only current ones; true: only ended ones
columns     name       the other end, linked, with its footnotes
            verb  share  status  period  date  deal         the relationship's own fields (the share is drawn as a bar)
            thumb  badges                                    the other end's picture, and its badges (hints.yaml)
            {label, prop}                                    a property of the other end's page
            {label, column}                                  a column above under another heading (label: Owner, column: name)
sort        former  -share  share  period  name  title       a leading "-" reverses; default: period, then name
view        table (default) | list | timeline
min         fewest rows worth a section (default 1)
props       property names of this page, shown as a two-column table; a property with no value is left out

A section with nothing to show is "" (no heading), as the built-in ones are. A mistake in a definition is an
error when the wiki loads, naming the section and the key, never a quietly empty section.

A relations section also takes its (edge, side) out of the default "other relationships" lists, on the pages that
show it, so the same links are not drawn twice (`section.covers()` says which).
"""
from __future__ import annotations

import html

from hydra import schema as hschema
from hydra.wiki import chips, deals, roles, views

e = html.escape

def _thumb(c, r) -> str:
    other = c.page(r.get("other")) if r.get("other") else None
    pic = views.image(other, small=True) if other else None
    return f"<img class=thumb src='{c.L.asset(pic)}' alt=''>" if pic else ""


def _badges(c, r) -> str:
    other = c.page(r.get("other")) if r.get("other") else None
    return "".join(ch.html() for ch in chips.badges(c.wiki, c.L, other, c)) if other else ""


COLUMNS = {                      # name -> (heading, cell(c, r) -> html)
    "thumb": ("", _thumb),
    "badges": ("Badges", _badges),
    "name": ("Name", lambda c, r: c.a(r) + c.sup(r["cites"])),
    "verb": ("Relationship", lambda c, r: e(str(r.get("verb") or ""))),
    "share": ("Share", lambda c, r: deals.share(r)),
    "status": ("Status", lambda c, r: deals.status_chip(c.wiki, r)),
    "period": ("Period", lambda c, r: e(deals.when(r))),
    "date": ("Date", lambda c, r: e(str(r.get("date") or ""))),
    "deal": ("Deal", lambda c, r: deals.deal_link(c.wiki, c, r)),
}
SORTS = {                        # name -> key(c, r), ascending
    "former": lambda c, r: deals._former(c.wiki, r),
    "share": lambda c, r: deals.pct(r) or 0,
    "period": lambda c, r: deals._order(c.wiki, r),
    "name": lambda c, r: c.wiki.title(r),
    "title": lambda c, r: c.wiki.title(r),
}
VIEWS = ("table", "list", "timeline")
KEYS = {"title", "relations", "columns", "sort", "view", "min", "props"}
REL_KEYS = {"edge", "side", "verb", "other", "former"}


def _fail(name: str, msg: str):
    raise ValueError(f"wiki.yaml define: {name}: {msg}")


def _edge(name: str, reg=None) -> str:
    """A role's current edge name (`ownership` -> Ownership), else the edge as written.
    `reg` is the page's registry; without one the base conf's roles apply."""
    r = reg.roles if reg is not None else roles
    return getattr(r, str(name).upper()) if str(name).upper() in roles.DEFAULTS else str(name)


def _values(c, v: dict) -> str:
    return (c.a(v) if v.get("h") else e(str(v.get("value") or ""))) + c.sup(v.get("cites") or [])


def _column(sec: str, col) -> tuple[str, object]:
    if isinstance(col, str):
        if col not in COLUMNS:
            _fail(sec, f"unknown column {col!r}; known: {sorted(COLUMNS)} or {{label, prop}}")
        return COLUMNS[col]
    if isinstance(col, dict) and col.get("column"):             # a built-in column under another heading
        head, cell = _column(sec, col["column"])
        return str(col.get("label") or head), cell
    if isinstance(col, dict) and col.get("prop"):
        prop = str(col["prop"])

        def cell(c, r):
            return "<br>".join(_values(c, x) for x in (c.values(r["other"], prop) if r.get("other") else []))
        return str(col.get("label") or prop), cell
    _fail(sec, f"a column is a name or {{label, prop}}, not {col!r}")


def build(name: str, spec: dict):
    """The section function for one definition, named `name` (panels and `sections:` find it by that)."""
    if not isinstance(spec, dict):
        _fail(name, "a mapping with title and relations or props")
    if bad := set(spec) - KEYS:
        _fail(name, f"unknown key(s) {sorted(bad)}; known: {sorted(KEYS)}")
    title = str(spec.get("title") or name.replace("_", " ").capitalize())
    rel, props = spec.get("relations"), spec.get("props")
    if bool(rel) == bool(props):
        _fail(name, "give either `relations` or `props`")
    head = f"<h2 id={name}>{e(title)}</h2>"
    if props:
        names = [props] if isinstance(props, str) else list(props)

        def section(p, c):
            rows = [f"<tr><th>{e(prop)}</th><td>{'<br>'.join(_values(c, v) for v in c.values(p, prop))}</td></tr>"
                    for prop in names if c.values(p, prop)]
            return head + f"<table class='wikitable'>{''.join(rows)}</table>" if rows else ""
        section.__name__ = name
        return section

    if not isinstance(rel, dict) or "edge" not in rel:
        _fail(name, "`relations` needs at least an `edge`")
    if bad := set(rel) - REL_KEYS:
        _fail(name, f"unknown relations key(s) {sorted(bad)}; known: {sorted(REL_KEYS)}")
    if rel.get("side") not in (None, "source", "target"):
        _fail(name, "relations.side is source or target")
    view = spec.get("view", "table")
    if view not in VIEWS:
        _fail(name, f"view is one of {VIEWS}")
    cols = [_column(name, x) for x in (spec.get("columns") or ["name", "period"])]
    order = spec.get("sort") or ["period", "name"]
    order = [order] if isinstance(order, str) else order
    keys = []
    for s in order:
        k = str(s).lstrip("-")
        if k not in SORTS:
            _fail(name, f"unknown sort {s!r}; known: {sorted(SORTS)}")
        keys.append((SORTS[k], str(s).startswith("-")))
    minimum = int(spec.get("min", 1))
    verbs = rel.get("verb")
    verbs = [verbs] if isinstance(verbs, str) else verbs
    edge_name, other, former = rel["edge"], rel.get("other"), rel.get("former")

    def pick(p, c):
        rs = c.rels(p, _edge(edge_name, c.reg), rel.get("side"), verbs)
        if other:
            rs = [r for r in rs if other in hschema.ancestors((c.page(r.get("other")) or {}).get("schema") or "")]
        if former is not None:
            rs = [r for r in rs if deals._former(c.wiki, r) == bool(former)]
        for key, rev in reversed(keys):                 # stable sorts, last key first
            rs = sorted(rs, key=lambda r: key(c, r), reverse=rev)
        return rs

    def section(p, c):
        rs = pick(p, c)
        if not rs or len(rs) < minimum:
            return ""
        if view == "table":
            th = "".join(f"<th>{e(h)}</th>" for h, _ in cols)
            trs = "".join("<tr>" + "".join(f"<td>{cell(c, r)}</td>" for _, cell in cols) + "</tr>" for r in rs)
            return head + f"<table class='wikitable'><tr>{th}</tr>{trs}</table>"
        if view == "list":
            return head + "<ul>" + "".join(
                "<li>" + " ".join(x for x in (cell(c, r) for _, cell in cols) if x) + "</li>" for r in rs) + "</ul>"
        ev = []
        for r in rs:
            for k, word in (("startDate", "from"), ("endDate", "until")):
                y = views.year(r.get(k) or (r.get("date") if k == "startDate" else None))
                if y:
                    ev.append((y, f"{word} {c.a(r)}{c.sup(r['cites'])}"))
        if not ev:
            return ""
        return head + "<ul class=timeline>" + "".join(
            f"<li><b>{c.year_link(y)}</b> {t}</li>" for y, t in sorted(ev, key=lambda x: x[0])) + "</ul>"
    section.__name__ = name
    sides = (rel["side"],) if rel.get("side") else ("source", "target")
    section.covers = lambda reg=None: {(_edge(edge_name, reg), x) for x in sides}
    return section


def register(defs: dict | None) -> None:
    """Make wiki.yaml `define:` sections known by name, replacing any this module added before."""
    for n in [n for n, f in views.SECTIONS.items() if getattr(f, "declared", False)]:
        del views.SECTIONS[n]
    if defs is not None and not isinstance(defs, dict):
        raise ValueError("wiki.yaml define: must be a mapping of section name to definition")
    for n, spec in (defs or {}).items():
        if n in views.SECTIONS:
            _fail(n, "that name is a built-in section; pick another")
        f = build(str(n), spec)
        f.declared = True
        views.SECTIONS[str(n)] = f
