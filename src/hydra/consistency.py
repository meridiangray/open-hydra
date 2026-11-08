"""consistency.py — facts that cannot all be true, found in the merged entities.

Each check reads only what the records state, and says which records state it;
nothing is changed or dropped. A source error (a mother recorded as a
father) and a wrong merge (two people's dates on one person) both show up here.

    facts.relationship-gender  a gendered relationship (father, wife, ...) whose relative has the other gender
    facts.parent-younger       a parent born in or after the child's birth year
    facts.parent-dead          a father dead over a year, or a mother dead, before the child was born
    facts.term-outside-life    a term (an Occupancy, Membership, Directorship, ...) that starts
                               before its person was born or after they died
    facts.terms-overlap        two holders of one post at the same time (info: co-holders and
                               acting holders are real, but so are wrong dates)
    facts.ancestor-cycle       someone recorded as their own ancestor

Dates are compared by their bounds (`1933` is all of 1933), so only a
certain contradiction is reported.
"""
from __future__ import annotations

from collections import defaultdict

from hydra import dates, kinship, layout, schema

TERM_START, TERM_END = ("startDate", "date"), ("endDate",)


def _issue(level, code, where, message):
    return {"level": level, "code": code, "file": f"{layout.COLLECTIONS_DIR}/", "where": where, "message": message}


def _lo(vals):
    b = [dates.bounds(v) for v in vals or ()]
    b = [x for x in b if x]
    return min(x[0] for x in b) if b else None


def _hi(vals):
    b = [dates.bounds(v) for v in vals or ()]
    b = [x for x in b if x]
    return max(x[1] for x in b) if b else None


def _year(iso):
    return dates.year(iso)


def check(ents: list[dict], kin: "kinship.Kinship | None" = None) -> list[dict]:
    """`ents`: the merged entities with links as ids (shape.entities.entities(r)). `kin`: what each
    Family word says (kinship.yaml; the template's when not given)."""
    kin = kin or kinship.load(None)
    by_id = {e["id"]: e for e in ents}
    props = lambda i: (by_id.get(i) or {}).get("properties") or {}
    name = lambda i: (props(i).get("name") or [i])[0]
    gender = lambda i: {g.lower() for g in props(i).get("gender") or []}
    born_lo = lambda i: _lo(props(i).get("birthDate"))
    born_hi = lambda i: _hi(props(i).get("birthDate"))
    died_hi = lambda i: _hi(props(i).get("deathDate"))
    died_hi = lambda i: _hi(props(i).get("deathDate"))
    out = []
    parents = defaultdict(set)
    terms = defaultdict(list)
    for e in ents:
        sc = schema.SCHEMA.get(e["schema"]) or {}
        edge = sc.get("edge")
        if not edge:
            continue
        p = e["properties"]
        src, tgt = p.get(edge["source"]) or [], p.get(edge["target"]) or []
        if schema.is_a(e["schema"], "Family"):
            for rel in (x.lower() for x in p.get("relationship") or []):
                for child in src:
                    for rel_id in tgt:
                        g = gender(rel_id)
                        want = kin.gender(rel)
                        if want and g and want not in g:
                            out.append(_issue("warning", "facts.relationship-gender", e["id"],
                                              f"{name(rel_id)} is recorded as {name(child)}'s {rel}, "
                                              f"but as {'/'.join(sorted(g))}"))
                        if kin.is_(rel, "parent"):
                            parents[child].add(rel_id)
                            cb, pb = born_hi(child), born_lo(rel_id)
                            if cb and pb and _year(pb) >= _year(cb):
                                out.append(_issue("warning", "facts.parent-younger", e["id"],
                                                  f"{name(rel_id)} ({rel}) is born {props(rel_id)['birthDate'][0]}, "
                                                  f"not before {name(child)} ({props(child)['birthDate'][0]})"))
                            dh, cl = died_hi(rel_id), born_lo(child)
                            grace = 1 if kin.gender(rel) == "male" else 0    # a father may die before the birth
                            if dh and cl and _year(dh) + grace < _year(cl):
                                out.append(_issue("warning", "facts.parent-dead", e["id"],
                                                  f"{name(rel_id)} ({rel}) died {props(rel_id)['deathDate'][0]}, "
                                                  f"before {name(child)} was born ({props(child)['birthDate'][0]})"))
            continue
        start, end = _lo([v for k in TERM_START for v in p.get(k) or []]), _hi([v for k in TERM_END for v in p.get(k) or []])
        if not (start or end):
            continue
        for who in src + tgt:
            if (by_id.get(who) or {}).get("schema") != "Person" and not schema.is_a((by_id.get(who) or {}).get("schema") or "Thing", "Person"):
                continue
            if start and born_lo(who) and _year(start) < _year(born_lo(who)):
                out.append(_issue("warning", "facts.term-outside-life", e["id"],
                                  f"{e['schema']} of {name(who)} starts {start[:4]}, before they were born "
                                  f"({props(who)['birthDate'][0]})"))
            if start and died_hi(who) and _year(start) > _year(died_hi(who)):
                out.append(_issue("warning", "facts.term-outside-life", e["id"],
                                  f"{e['schema']} of {name(who)} starts {start[:4]}, after they died "
                                  f"({props(who)['deathDate'][0]})"))
        if e["schema"] == "Occupancy" and start and end:
            for post in tgt:
                terms[post].append((start, end, e["id"], src[0] if src else ""))
    for post, ts in terms.items():
        ts.sort()
        for (s1, e1, id1, h1), (s2, e2, id2, h2) in zip(ts, ts[1:]):
            if h1 != h2 and _year(s2) < _year(e1):     # whole years apart: a handover year is no overlap
                out.append(_issue("info", "facts.terms-overlap", id2,
                                  f"{name(post)}: {name(h2)} from {s2[:4]} while {name(h1)} held it until {e1[:4]}"))
    # someone their own ancestor
    seen, stack, reported = set(), set(), set()

    def visit(x, path):
        if x in stack:
            cyc = path[path.index(x):]
            key = frozenset(cyc)
            if key not in reported:
                reported.add(key)
                out.append(_issue("warning", "facts.ancestor-cycle", x,
                                  "recorded as their own ancestor: " + " -> ".join(name(i) for i in cyc + [x])))
            return
        if x in seen:
            return
        seen.add(x)
        stack.add(x)
        for p_ in sorted(parents.get(x, ())):
            visit(p_, path + [x])
        stack.discard(x)

    for child in sorted(parents):
        visit(child, [])
    return out
