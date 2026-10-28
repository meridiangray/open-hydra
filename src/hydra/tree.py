"""tree.py — an archive's hierarchy as text, from its last build (never builds).

    hydra-ctl tree [<archive-dir>] [type] [relationship...] [search]
        [--read declared|generic] [--format text|json|mermaid] [--ascii]
        [--vertical] [--lateral] [--direction TD|LR] [--singletons]

Default: the record tree, every node under its primary parent as the read
placed it. A type word (`tree person`, `tree organization`, any capitalisation)
starts it at each node of that type not below another of that type; a search
(`tree gid`) at the records it names (other fields only when no name matches).
A relationship word (`tree family`, `tree ownership employment`) draws only
the links of those kinds and only the records in them, each linked group apart.
The chart draws each record once, under one parent; every other vertical
relationship it has is listed under it in columns, `also  X   Ownership   role
why`, where why says it is not the drawn parent: `rejected` (your decision),
`cycle` (a loop), `earlier` (a different period), `rules` (the position rules),
`sideways` (a family link that is not parent and child). Names only, never
expanded, so nothing repeats or loops. The position tree is `hydra-ctl positions`
(`position_tree` here is its model). `--format mermaid` draws the same records
as a flowchart (`record_mermaid`): solid lines to primary parents, dotted for
the also rows and sideways links; `--vertical` or `--lateral` keeps one kind.
Ported from the original hydra's `tree`, minus its terminal colours."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import yaml

from hydra import layout, query, resources, schema
from hydra import sources as sources_mod
from hydra.cli import style
from hydra.review import ids, verdicts as vd
from hydra.shape.rules import _mesc
from hydra.structure import fold

READS = layout.READS


def _load(root: Path, read: str) -> tuple[dict, dict]:
    p = root / READS[read]
    if not p.is_file():
        raise SystemExit(f"hydra: {p} not found; build the archive first")
    parsed = root / layout.PARSED_YAML
    rules = (yaml.safe_load(parsed.read_text(encoding="utf-8")) or {}) if parsed.is_file() else {}
    return json.loads(p.read_text(encoding="utf-8")), rules


def position_tree(ir: dict, parsed: dict | None = None, with_nodes: bool = False) -> list[dict]:
    """The read's positions as a nested model [{name, outside, source, titles,
    children, nodes?, dup?}]. Roots are positions with nothing above; children
    sorted by name; a position reached a second time is marked `dup` and not
    expanded. `parsed` (parsed.yaml) adds titles and sources."""
    pos = (ir.get("rules") or {}).get("positions") or {}
    extra = (parsed or {}).get("positions") or {}
    kids: dict[str, list[str]] = {}
    for name, d in pos.items():
        for u in d.get("uppers") or []:
            kids.setdefault(u, []).append(name)
    nodes = ir.get("nodes") or {}
    seen: set[str] = set()

    def node(name):
        d, x = pos.get(name) or {}, extra.get(name) or {}
        e = {"name": name, "outside": bool(d.get("outside")), "source": x.get("source"),
             "titles": list(x.get("titles") or []), "children": []}
        if with_nodes:
            e["nodes"] = sorted(({"caption": n.get("caption"), "schema": n.get("schema")}
                                 for n in nodes.values() if n.get("position") == name),
                                key=lambda n: str(n["caption"]).lower())
        if name in seen:
            e["dup"] = True
            return e
        seen.add(name)
        e["children"] = [node(c) for c in sorted(kids.get(name, []), key=str.lower)]
        return e

    roots = sorted((n for n, d in pos.items() if not d.get("uppers")),
                   key=lambda n: ((extra.get(n) or {}).get("source") == "implied", str(n).lower()))
    return [node(r) for r in roots]


def starts_of(ir: dict, kinds=(), text: str = "", search: str = "all") -> list[str]:
    """Where a record tree starts. A search (`text`, kept to `kinds`): the matching
    nodes, best first; how far it looks is `search` (query.SEARCH). Types alone:
    every node of those types with no ancestor of those types (`tree person`:
    each person not below another person), in the read's order."""
    nodes = ir.get("nodes") or {}
    if text:
        from hydra.claims import match
        named = match(nodes, text, kinds, fields=False)                         # names first
        return named or ([] if search == "names" else match(nodes, text, kinds, free_text=search == "all"))
    out, seen = [], set()

    def walk(i, covered):
        if i in seen or i not in nodes:
            return
        seen.add(i)
        hit = query.of_type(nodes[i].get("schema", ""), kinds)
        if hit and not covered:
            out.append(i)
        for k in nodes[i].get("kids") or []:
            walk(k, covered or hit)

    for r in ir.get("roots") or []:
        walk(r, False)
    return out


def _cut(ir: dict) -> set:
    """(child, parent) pairs cut so the chart has no loop: by the cycle check, and
    by the build's last guard."""
    report = ir.get("report") or {}
    cut = {(c["child"], c["parent"]) for c in report.get("cut") or []}
    return cut | {(c[0], c[1]) for c in ((report.get("cycles") or {}).get("cut") or []) if len(c) >= 2}


# ---- `tree ownership`, `tree family`...: only the links of one kind of relationship ----

PREFER = {"ownership": "Ownership", "membership": "Membership", "employment": "Employment",
          "directorship": "Directorship", "occupancy": "Occupancy", "family": "Family"}
# FtM's Family is sideways; only its `relationship` text says who is above whom.
# That text describes the `relative` from the `person`'s side ("father": the
# relative is the person's father). These words, and only these, make it
# vertical; any other (spouse, sibling, uncle, in-law) stays sideways.
FAMILY_CHILD = {"son", "daughter", "child"}       # the relative is the person's child
FAMILY_PARENT = {"father", "mother", "parent"}    # the relative is the person's parent


def _family_roles(root: Path) -> dict[str, str]:
    """{Family record id: its `relationship` text}, from the build's claims."""
    p = Path(root) / layout.CLAIMS_JSONL
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines() if p.is_file() else ():
        c = json.loads(line)
        if c.get("prop") == "relationship" and c.get("schema") == "Family" and c.get("record"):
            out.setdefault(c["record"], c.get("value") or "")
    return out


def _above(r: dict, direction: dict, family_roles: dict) -> bool:
    """True when the other end of relationship `r` sits above the node holding it."""
    via = r.get("via") or ""
    if via == "Family":
        role = str(family_roles.get(r.get("record")) or "").strip().lower()
        if role in FAMILY_CHILD:
            return r.get("label") == "relative"   # this node is the child
        if role in FAMILY_PARENT:
            return r.get("label") == "person"
        return False
    d = fold.infer_direction(via, direction)
    return d.get("kind") in ("vertical", "dual") and r.get("label") == d.get("child_prop")


def _links(rid: str, n: dict, kind: str, nodes: dict, direction: dict, roles: dict) -> list[dict]:
    """Every `kind` relationship (a PREFER key) of node `rid`: [{at, kind, role,
    up, label, of}], `up` True when the other end sits above it, False when it is
    below, None when sideways (family words other than parent/child). For Family,
    `role` is the record's word and `of` says whom it describes: "at" (the other
    end; this node is the `person`) or "self" (this node, the `relative`)."""
    want, out = PREFER[kind], []
    for r in n.get("rels") or []:
        if r.get("via") != want or r.get("at") not in nodes or r["at"] == rid:
            continue
        fam = want == "Family"
        role = (roles.get(r.get("record")) if fam else r.get("role")) or ""
        flip = dict(r, label="relative" if r.get("label") == "person" else "person") if fam else None
        up = True if _above(r, direction, roles) else \
            False if (flip and _above(flip, direction, roles)) or (not flip and fold.infer_direction(
                want, direction).get("kind") in ("vertical", "dual")) else None
        out.append({"at": r["at"], "kind": kind, "role": str(role).strip(), "up": up, "label": r.get("label"),
                    "of": ("at" if r.get("label") == "person" else "self") if fam else "at"})
    return out


def _says(x: dict, about: str) -> str:
    """Link `x`'s role, worded for `about`: "self" (the line it is drawn on) or "at"
    (the record it names). A family word describing the other end is turned
    round for parent and child, so "father" on the child's own line reads
    "child (father)" and "son" naming the parent reads "parent (son)"."""
    role = x["role"]
    if x["kind"] != "family" or x["of"] == about or not role:
        return role
    w = role.lower()
    return f"child ({role})" if w in FAMILY_PARENT else f"parent ({role})" if w in FAMILY_CHILD else role


def prefer(ir: dict, kinds, direction: dict, verdicts: dict | None = None,
           family_roles: dict | None = None) -> dict:
    """A copy of the read drawing only the links of `kinds` (PREFER keys, first
    listed first) and only the records in them: each record goes under a parent
    of the first kind it has one of (the first by name when there are several of
    that kind), labelled (`link`); its other links of those kinds are
    `only_also`, and its sideways family links (not parent/child) `sideways`,
    on the `person` end. Every record at either end of one of these links is
    drawn, so no relative or second parent is left out; a record with none is
    left out (`report.left_out` counts them). Records are grouped
    (`report.groups`): those joined by any drawn or listed link share a group,
    drawn together, so one family reads together. Never a parent you
    rejected or one cut from a loop, and never a move that would close a loop.
    Display only: the build, its files and your decisions are untouched."""
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    roles = family_roles or {}
    out = copy.deepcopy(ir)
    nodes, cut = out.get("nodes") or {}, _cut(ir)
    was = {rid: n.get("pid") for rid, n in nodes.items()}   # the plain tree's parent: kept when it is a pick
    pid: dict[str, str | None] = dict.fromkeys(nodes)        # only the links chosen so far: a loop check on them
    cap = lambda i: str(nodes[i].get("caption") or i).lower()
    links = {rid: [x for k in kinds for x in _links(rid, n, k, nodes, direction, roles)] for rid, n in nodes.items()}
    usable = lambda rid, a: (vd.status_of(verdicts or {}, ids.place_key(rid, a)) != "rejected"
                             and (rid, a) not in cut)

    def closes_loop(rid, a):
        up, seen = a, {rid}
        while up and up not in seen:
            seen.add(up)
            up = pid.get(up)
        return bool(up)

    chosen: dict[str, dict] = {}
    for rid in sorted(nodes):
        pick = None
        for k in kinds:
            opts = sorted((x for x in links[rid] if x["kind"] == k and x["up"] and usable(rid, x["at"])),
                          key=lambda x: (cap(x["at"]), x["at"], x["role"]))
            if not opts:
                continue
            here = [x for x in opts if x["at"] == was[rid] and not closes_loop(rid, x["at"])]
            pick = here[0] if here else next((x for x in opts if not closes_loop(rid, x["at"])), None)
            if pick:
                break
        if pick:
            chosen[rid] = pick
            pid[rid] = pick["at"]
    side = {rid: [x for x in links[rid] if x["up"] is None and x["label"] == "person"] for rid in nodes}
    drawn = {rid for rid in nodes if links[rid]}       # every record at either end of a link of these kinds
    rep = out.setdefault("report", {})
    rep["left_out"] = len(nodes) - len(drawn)
    for rid in drawn:
        n = nodes[rid]
        n.pop("position", None)                       # the link label says it; a position is the plain tree's
        if rid in chosen:
            n["link"] = f"{chosen[rid]['kind']}: {_says(chosen[rid], 'self')}".rstrip(": ")
        rows = {}
        for x in links[rid]:
            if x["up"] and x["at"] != pid[rid]:
                rows.setdefault((x["at"], x["kind"], x["role"]), {
                    "at": x["at"], "cap": nodes[x["at"]].get("caption") or x["at"], "via": PREFER[x["kind"]],
                    "role": _says(x, "at"),
                    "why": "" if usable(rid, x["at"]) else ("rejected" if (rid, x["at"]) not in cut else "cycle")})
        n["only_also"] = sorted(rows.values(), key=lambda x: (str(x["cap"]).lower(), x["at"], x["via"], x["role"]))
        n["sideways"] = sorted(({"at": x["at"], "cap": nodes[x["at"]].get("caption") or x["at"], "role": x["role"]}
                                for x in {(x["at"], x["role"]): x for x in side[rid]}.values()),
                               key=lambda x: (str(x["cap"]).lower(), x["at"], x["role"]))
    for rid, n in nodes.items():
        n["pid"] = pid[rid] if pid[rid] in drawn else None
        if rid in chosen:
            n["placement"] = {**(n.get("placement") or {}), "criteria": "only " + " ".join(kinds)}
    order = {rid: i for i, rid in enumerate(ir.get("roots") or [])}
    for rid, n in nodes.items():                      # kids: kept order, then the newcomers by name
        kept = [k for k in n.get("kids") or [] if k in drawn and pid.get(k) == rid]
        new = sorted((k for k in drawn if pid[k] == rid and k not in kept), key=lambda i: (cap(i), i))
        n["kids"] = kept + new
    roots = [rid for rid in drawn if not nodes[rid]["pid"]]
    # group the roots: one union-find over every drawn, listed or sideways link
    up_of: dict[str, str] = {}

    def find(i):
        while up_of.get(i, i) != i:
            i = up_of[i]
        return i
    for rid in drawn:
        for j in [pid[rid]] + [x["at"] for x in nodes[rid]["only_also"] + nodes[rid]["sideways"]]:
            if j in drawn:
                a, b = find(rid), find(j)
                if a != b:
                    up_of[max(a, b)] = min(a, b)
    key = lambda i: (order.get(i, len(order)), cap(i), i)
    first: dict[str, tuple] = {}
    for r in roots:
        first[find(r)] = min(first.get(find(r), key(r)), key(r))
    out["roots"] = sorted(roots, key=lambda i: (first[find(i)], key(i)))
    gid = {g: k for k, g in enumerate(sorted(first, key=first.get))}
    rep["groups"] = {rid: gid[find(rid)] for rid in sorted(drawn)}
    out["nodes"] = {rid: n for rid, n in nodes.items() if rid in drawn}
    return out


def also_under(ir: dict, direction: dict, verdicts: dict | None = None) -> dict[str, list[dict]]:
    """{node id: every vertical relationship it is the lower end of, other than the
    one it is drawn under}: [{at, cap, via, role, why}]. Read from the node's own
    `rels` (every relationship the build resolved, whatever the chart chose), with
    the direction `direction.yaml` gives (`fold.infer_direction`, the build's own
    rule), so the chart's one-parent drawing never hides a relationship. `why`
    says why it is not the drawn parent: "rejected" (your decision), "cycle" (cut
    so the chart has no loop), "earlier" (its dates do not overlap the drawn
    one), "rules" (the position rules drew the record under a person instead),
    or "" (another parent at the same time; the chart shows one)."""
    nodes, report = ir.get("nodes") or {}, ir.get("report") or {}
    earlier = {(s["child"], o) for s in report.get("sequential") or [] for o in s.get("other") or []}
    cut = _cut(ir)
    out: dict[str, list[dict]] = {}
    for rid, n in nodes.items():
        by_rule = ((n.get("placement") or {}).get("criteria") or "").startswith("rules:")
        rows = {}
        for r in n.get("rels") or []:
            d = fold.infer_direction(r.get("via") or "", direction)
            if d.get("kind") not in ("vertical", "dual") or r.get("label") != d.get("child_prop"):
                continue                              # sideways, or this record is the upper end
            if r.get("at") == n.get("pid") or r.get("at") not in nodes:
                continue
            at = r["at"]
            why = ("rejected" if vd.status_of(verdicts or {}, ids.place_key(rid, at)) == "rejected"
                   else "cycle" if (rid, at) in cut else "earlier" if (rid, at) in earlier
                   else "rules" if by_rule else "")
            rows.setdefault((at, r.get("via"), r.get("role") or ""),
                            {"at": at, "cap": nodes[at].get("caption") or at, "via": r.get("via"),
                             "role": r.get("role") or "", "why": why})
        if rows:
            out[rid] = sorted(rows.values(), key=lambda x: (str(x["cap"]).lower(), x["at"], x["via"], x["role"]))
    return out


def _also_rows(xs: list[dict]) -> list[str]:
    """A record's other parents as aligned columns: the parent, the relationship,
    its role, and why it is not the drawn one (rejected, cycle, earlier). `rules`
    is left out: the record's own line already shows the position that placed it."""
    cols = [[x["cap"], x["via"], x["role"] or "", "" if x["why"] == "rules" else x["why"] or ""] for x in xs]
    w = [max(len(c[i]) for c in cols) for i in range(4)]
    return [("also  " + "   ".join(f"{c[i]:<{w[i]}}" for i in range(4))).rstrip() for c in cols]


def _plain(model: list[dict]) -> list[dict]:
    """The tree model without its color parts (JSON stays as it was)."""
    return [{k: (_plain(v) if k == "children" else v) for k, v in e.items() if k != "_parts"} for e in model]


def drawn_ids(ir: dict, starts=None) -> list[str]:
    """The records a record tree draws, in drawing order."""
    nodes, out, seen = ir.get("nodes") or {}, [], set()

    def walk(i):
        if i in seen or i not in nodes:
            return
        seen.add(i)
        out.append(i)
        for k in nodes[i].get("kids") or []:
            walk(k)

    for r in (ir.get("roots") or [] if starts is None else starts):
        walk(r)
    return out


def record_tree(ir: dict, starts=None, also: dict | None = None) -> list[dict]:
    """The read's nodes under their primary parents, as the read ordered them;
    from `starts` instead of the roots when given. `also` (also_under) lists,
    under each node, the relationships its one drawn parent leaves out."""
    nodes = ir.get("nodes") or {}
    seen: set[str] = set()

    def node(i):
        n = nodes.get(i) or {}
        parts = [(n.get("caption") or i, "name"), (f" ({n.get('schema') or '?'})", "aside")]
        stub = i.startswith("stub:")                  # a name no record has, graduated (stubs.py)
        if n.get("position"):
            parts += [(" — ", ""), (n["position"], "accent")]
        if n.get("link"):                             # a relationship chart: the link it is drawn by
            kind, _, role = n["link"].partition(": ")
            parts += [("   ", ""), (PREFER.get(kind, kind) + (f"   {role}" if role else ""), "accent")]
        if stub:
            parts += [("   ", ""), ("stub", "note")]
        e = {"name": "".join(t for t, _ in parts), "_parts": parts,     # plain name for JSON; parts for color
             "outside": False, "source": None, "titles": [], "children": []}
        rows = list((also or {}).get(i) or [])
        rows += [{**x, "via": "Family", "why": "sideways"} for x in n.get("sideways") or []]   # not parent/child
        if rows:
            e["also"] = _also_rows(rows)
        if i in seen:
            e["dup"] = True
            return e
        seen.add(i)
        e["children"] = [node(k) for k in n.get("kids") or [] if k in nodes]
        return e

    groups = (ir.get("report") or {}).get("groups") or {}
    tops = [r for r in (ir.get("roots") or [] if starts is None else starts) if r in nodes]
    tree = [node(r) for r in tops]
    if len({groups.get(r) for r in tops}) > 1:        # a relationship chart: records linked read together
        for e, r in zip(tree, tops):
            e["group"] = groups.get(r)
    return tree


def render(tree: list[dict], ascii: bool = False) -> str:
    """The record tree model as text: box-drawing, or `|-- \\-- |` with ascii."""
    tee, ell, vert = ("|-- ", "\\-- ", "|   ") if ascii else ("├── ", "└── ", "│   ")
    lines: list[str] = []

    def rec(n, prefix, conn):
        lines.append(style.aside(prefix + conn) + style.styled(n["_parts"] + ([(" ^", "aside")] if n.get("dup") else [])))
        inner = prefix if not conn else prefix + ("    " if conn == ell else vert)
        for a in n.get("also") or []:                 # names only: never expanded, so never a loop
            lines.append(style.aside(f"{inner}{vert[0] if n.get('children') else ' '} {a}"))
        for i, c in enumerate(n.get("children") or []):
            rec(c, inner, ell if i == len(n["children"]) - 1 else tee)

    for k, r in enumerate(tree):
        if k and "group" in r and r["group"] != tree[k - 1].get("group"):
            lines.append("")                          # a blank line between unconnected groups
        rec(r, "", "")
    return "\n".join(lines) + "\n"


def record_mermaid(ir: dict, starts=None, also: dict | None = None, only: bool = False,
                   vertical: bool = True, lateral: bool = True, direction: str = "TD",
                   singletons: bool = False, label: str = "") -> str:
    """The record tree as a Mermaid flowchart: what `record_tree` draws. Solid
    `parent --> record` for each primary parent, labelled by its placement
    record's role (`link` in a relationship chart, `only`); dotted for the rest:
    `X -.-> record` for each other parent in `also`, and `a -.- b`, no arrowhead,
    for each sideways link (`lateral`, or `sideways` in a relationship chart).
    A link is drawn once, and only when both ends are drawn. Records left with no
    line are a comment unless `singletons`."""
    nodes = ir.get("nodes") or {}
    drawn = drawn_ids(ir, starts)
    here = set(drawn)
    mids: dict[str, str] = {}
    for i in drawn:                                   # Mermaid ids from the entity ids, unique
        m = "".join(c if c.isalnum() else "_" for c in i.split(":", 1)[-1].lower()).strip("_")
        m = m if m[:1].isalpha() and m != "end" else f"n_{m}"
        k, base = 2, m
        while m in mids.values():
            m, k = f"{base}_{k}", k + 1
        mids[i] = m

    def role_of(n, record):                           # the role, or Associate/Family's wording, on a record
        return next((r.get("role") or r.get("relationship") or "" for r in n.get("rels") or []
                     if r.get("record") == record and (r.get("role") or r.get("relationship"))), "")

    edges: list[tuple] = []
    placed: set = set()
    for i in drawn:
        n = nodes[i]
        for k in n.get("kids") or []:
            if k not in here:
                continue
            kn = nodes[k]
            recs = (kn.get("placement") or {}).get("records") or []
            placed.update(recs)
            if only:
                kind, _, role = (kn.get("link") or "").partition(": ")
                loft = role or PREFER.get(kind, kind)
            else:
                loft = next((role_of(kn, r) for r in recs if role_of(kn, r)), "")
            edges.append((i, k, loft, "-->", vertical))
    for i in drawn:
        for x in (also or {}).get(i) or []:           # other parents; labelled from the data only, never
            if x["at"] in here:                       # `why` (a review preference, not a fact)
                edges.append((x["at"], i, x.get("role") or (x.get("via") if only else ""), "-.->", lateral))
    seen: set = set()
    for i in drawn:
        n = nodes[i]
        if only:
            ties = [(x["at"], x.get("role") or "Family", (i, x["at"], x.get("role"))) for x in n.get("sideways") or []]
        else:
            ties = [(t["to"], t.get("relationship") or role_of(n, t.get("record")), t.get("record"))
                    for t in n.get("lateral") or []
                    if not t.get("dup") and t.get("record") not in placed]   # dup: a proposed merge, not a link
        for to, loft, key in ties:
            pair = frozenset((i, to))
            if to in here and to != i and (key, pair) not in seen:
                seen.add((key, pair))
                edges.append((i, to, loft, "-.-", lateral))
    edges = [e for e in edges if e[4]]

    def box(i):
        n = nodes[i]
        sub = f"<br/><i>{_mesc(n['title'])}</i>" if n.get("title") else ""   # the break itself unescaped
        return f'    {mids[i]}["{_mesc(n.get("caption") or i)}{sub}"]'

    linked = {x for a, b, *_ in edges for x in (a, b)}
    out = [f"flowchart {direction}"]
    if label:
        out.append(f"    %% record tree — {_mesc(label)} (GENERATED)")
    out += [box(i) for i in drawn if i in linked or singletons]
    out += [f"    {mids[a]} {arrow}" + (f'|"{_mesc(loft)}"|' if loft else "") + f" {mids[b]}"
            for a, b, loft, arrow, _ in edges]
    alone = [str(nodes[i].get("caption") or i) for i in drawn if i not in linked]
    if alone and not singletons:
        out.append("    %% no links: " + ", ".join(alone))
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl tree",
                                 description="An archive's hierarchy, from its last build.")
    ap.add_argument("words", nargs="*", metavar="[dir] [type] [relationship] [search]",
                    help="an archive (optional); a type (person, organization...) starts the tree at the "
                         "top-most of that type; a relationship (" + ", ".join(PREFER) + ") draws only "
                         "those links and the records in them; anything else is a search")
    ap.add_argument("--read", choices=tuple(READS), default="declared")
    ap.add_argument("--format", choices=("text", "json", "mermaid"), default="text")
    ap.add_argument("--ascii", action="store_true", help="|-- \\-- | instead of box-drawing")
    ap.add_argument("--vertical", action="store_true", help="mermaid: only the solid primary-parent lines")
    ap.add_argument("--lateral", action="store_true", help="mermaid: only the dotted lines (other parents, sideways)")
    ap.add_argument("--direction", choices=("TD", "LR"), default="TD", help="mermaid: top-down or left-right")
    ap.add_argument("--singletons", action="store_true", help="mermaid: draw records with no line instead of a comment")
    ap.add_argument("--stubs", action="store_true",
                    help="also draw the names no record has where their links would put them (nothing saved)")
    query.add_search_flags(ap)
    a = ap.parse_intermixed_args(argv)
    words = list(a.words)
    lead = words.pop(0) if words and resources.names_archive(words[0]) else None
    words, with_sources = sources_mod.take_word(words)        # `tree organization sources`
    if with_sources and a.format == "mermaid":
        raise SystemExit("hydra: sources has no mermaid form; leave out `sources` or use --format text|json")
    note = sys.stderr if a.format == "mermaid" else sys.stdout   # keep `> chart.mmd` a chart
    follow = list(dict.fromkeys(w.lower() for w in words if w.lower() in PREFER))   # in the order given
    words = [w for w in words if w.lower() not in PREFER]
    root = resources.ensure_built(resources.archive(lead, read_only=True))
    ir, _ = _load(root, a.read)
    if a.stubs:                                       # a preview: every stub graduated as what it fits, in memory
        from hydra import build, stubs as stubs_mod
        cap: dict = {}
        preview = {e["slug"]: e["fits"] for e in stubs_mod.found(root) if e["fits"]}
        build.build_archive(root, write=False, capture=cap, stubs=preview)
        ir = cap["reads"][a.read]
    starts = None
    schema.load(root=root)                            # infer_direction reads each edge's two ends from it
    fam = root / layout.DIRECTION
    direction = fold.load_direction(fam if fam.is_file() else None)
    verdicts, _ = vd.load(root)
    if follow:
        ir = prefer(ir, follow, direction, verdicts, _family_roles(root) if "family" in follow else {})
    if words:
        kinds, text = query.split(words)
        starts = starts_of(ir, kinds, text, query.search_mode(root, a))
        if not starts:
            print("no record matches", file=note)
            return 0
    also = ({rid: n["only_also"] for rid, n in (ir.get("nodes") or {}).items() if n.get("only_also")}
            if follow else also_under(ir, direction, verdicts))
    tree = record_tree(ir, starts, also)
    counts = None
    if follow:
        counts = {"only": follow, "links": sum(1 for n in ir["nodes"].values() if n.get("link")),
                  "drawn": len(ir["nodes"]), "no link": ir["report"].get("left_out") or 0}
        if not ir["nodes"] and a.format != "json":
            print(f"no {' or '.join(follow)} links", file=note)
            return 0
    if counts and a.format == "text":
        head = ["only", "links", "drawn", "no link"]
        row = [" ".join(follow)] + [str(counts[h]) for h in head[1:]]
        w = [max(len(h), len(x)) for h, x in zip(head, row)]
        cell = lambda xs: "  " + "   ".join(f"{x:<{w[i]}}" if i == 0 else f"{x:>{w[i]}}" for i, x in enumerate(xs))
        print(style.aside(cell(head)) + "\n" + cell(row) + "\n")
    shown = drawn_ids(ir, starts) if with_sources else []
    if a.format == "json":
        doc = {"tree": _plain(tree)}
        if counts:
            doc["counts"] = counts
        if with_sources:
            doc["sources"] = sources_mod.show_for(root, shown, "json")
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    elif a.format == "mermaid":
        both = a.vertical == a.lateral                # neither flag, or both: every line
        sys.stdout.write(record_mermaid(ir, starts, also, only=bool(follow), vertical=both or a.vertical,
                                        lateral=both or a.lateral, direction=a.direction,
                                        singletons=a.singletons, label=root.name))
    else:
        sys.stdout.write(render(tree, ascii=a.ascii))
        if with_sources:
            sources_mod.show_for(root, shown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
