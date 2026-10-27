"""match.py — how two records are compared, and which kinds may merge.

`resolve_reference` turns an entity-typed value into a record id (identifier,
then exact name, then word-subset; several fits are `ambiguous`, none
`unresolved`). `decide` turns one candidate pair into a sameAs status. The
compatibility helpers keep a merge group to one kind: a generic `LegalEntity`
may become a `Person`, a `Person` and a `Company` never each other."""
from __future__ import annotations

from hydra import schema
from hydra.identity import index as index_mod, order, types


def id_link(rec: dict | None, prop: str, value: str, range_: str | None,
            indices: dict[str, index_mod.ClassIndex]) -> str | None:
    """The record a link value was written as the id of (`ingest.link_ids` keeps
    it), when that record fits `range_`; else None, and the value is resolved by
    name as usual."""
    target = (((rec or {}).get("_id_links") or {}).get(prop) or {}).get(value)
    if target is None:
        return None
    for idx in indices.values():
        hit = idx.records.get(target)
        if hit is not None:
            return target if not range_ or schema.is_a(hit.get("schema") or "Thing", range_) else None
    return None


def resolve_reference(value: str, range_: str, schema_universe: list[str],
                       indices: dict[str, index_mod.ClassIndex]) -> tuple[str | None, str, list[str]]:
    """A raw match/distinct-category entity-typed property value, plus its
    declared `range` -> (resolved record id or None, how, all candidates
    considered). `how` in {"identifier", "name-exact", "name-subset",
    "ambiguous", "unresolved"}. Only probes classes already in `indices`
    (i.e. already-finalized earlier passes/classes) -- order.py guarantees
    anything a match/distinct-promoted entity property ranges over is
    resolved first, so this never needs to look ahead."""
    concrete = order.concrete_classes_for_range(range_, schema_universe)

    id_hits: list[str] = []
    for cname in sorted(concrete):
        idx = indices.get(cname)
        if idx:
            id_hits += sorted(idx.match_value(value, "identifier"))
    if id_hits:
        return (id_hits[0], "identifier", id_hits) if len(id_hits) == 1 else (None, "ambiguous", id_hits)

    exact_hits, subset_hits = [], []
    for cname in sorted(concrete):
        idx = indices.get(cname)
        if not idx:
            continue
        for rid in sorted(idx.subset_hits(value)):
            best = None
            for n in idx.name_values.get(rid, []):
                cmp = types.compare_name(value, n)
                if cmp.signal is types.Signal.MATCH:
                    if cmp.how == "exact":
                        best = "exact"
                        break
                    best = best or "subset"
            if best == "exact":
                exact_hits.append(rid)
            elif best == "subset":
                subset_hits.append(rid)

    if exact_hits:
        return (exact_hits[0], "name-exact", exact_hits) if len(exact_hits) == 1 else (None, "ambiguous", exact_hits)
    if subset_hits:
        return (subset_hits[0], "name-subset", subset_hits) if len(subset_hits) == 1 else (None, "ambiguous", subset_hits)
    return None, "unresolved", []


def compare_detail(rec_a: dict, rec_b: dict, prop_classes: dict, resolved: dict):
    """-> (conflict, match_hows, clashes). `resolved` maps (record id, prop) to
    that record's resolve_reference() result for entity-typed match/distinct
    properties; `clashes` names every distinct property whose two values
    disagree, `[{prop, a, b}]`."""
    conflict = False
    match_hows: list[str] = []
    clashes: list[dict] = []
    names_a, names_b = [], []          # (value, weak) from every name-typed match field
    md = getattr(prop_classes, "md", None)
    for prop, pc in (md if md is not None else prop_classes.items()):
        if not (pc.match or pc.distinct):
            continue
        va = (rec_a.get("properties") or {}).get(prop) or []
        vb = (rec_b.get("properties") or {}).get(prop) or []
        if pc.ftm_type == "name":       # never a conflict; pooled across fields below
            if pc.match:
                names_a += [(v, prop in WEAK_NAMES) for v in va]
                names_b += [(v, prop in WEAK_NAMES) for v in vb]
            continue
        if not va or not vb:
            continue
        if pc.ftm_type == "entity":
            ra = resolved.get((rec_a["id"], prop))
            rb = resolved.get((rec_b["id"], prop))
            ida = ra[0] if ra else None
            idb = rb[0] if rb else None
            if ida is None or idb is None:
                continue  # unresolved -> neutral, never a conflict (types.py philosophy)
            if pc.distinct and ida != idb:
                conflict = True
                clashes.append({"prop": prop, "a": va, "b": vb})
            if pc.match and ida == idb:
                match_hows.append("entity-exact")
            continue
        for x in va:
            for y in vb:
                cmp = types.compare(pc.ftm_type, x, y)
                if cmp.signal is types.Signal.CONFLICT and pc.distinct:
                    conflict = True
                    if not any(c["prop"] == prop for c in clashes):
                        clashes.append({"prop": prop, "a": va, "b": vb})
                if cmp.signal is types.Signal.MATCH and pc.match:
                    st = types.strength(pc.ftm_type)
                    match_hows.append(cmp.how if st == "name" else f"{st}-{cmp.how}:{pc.ftm_type}")
    return conflict, _name_hows(names_a, names_b) + match_hows, clashes


def signature(rec: dict, prop_classes) -> tuple[tuple, frozenset]:
    """A record's match signature for may_match(): the word sets of its name and
    address values, and its normalized exact values. Computed once per record."""
    props = rec.get("properties") or {}
    words, exact = [], set()
    for prop, pc in prop_classes.md:
        if not pc.match:
            continue
        vals = props.get(prop) or ()
        if pc.ftm_type in types.TOKEN_TYPES:
            words += [types.name_key(v)[1] for v in vals]
        elif pc.ftm_type in types.EXACT_TYPES:
            norm = types.NORMALIZERS[pc.ftm_type]
            exact |= {(pc.ftm_type, norm(v)) for v in vals}
    return tuple(words), frozenset(exact)


def may_match(sig_a: tuple, sig_b: tuple) -> bool:
    """A cheap necessary condition for decide() to return a row, valid when both
    records are of one class whose match properties are all name, address or
    exact-value types (`PropMap.token_safe`). Then a row needs a name or address
    value of one whose words are a subset of (or equal to) one of the other's, or
    an equal exact value. Checked across all such properties at once, so it can
    only say yes too often, never no wrongly. Takes two `signature()`s."""
    words_a, exact_a = sig_a
    words_b, exact_b = sig_b
    if exact_a & exact_b:
        return True
    return any(x <= y or y <= x for x in words_a for y in words_b)


WEAK_NAMES = frozenset({"weakAlias"})
_NAME_RANK = {"exact": 0, "subset": 1, "weak-exact": 2}


def _name_hows(names_a: list, names_b: list) -> list[str]:
    """Every name-to-name match between two records, whichever fields hold the
    names (one record's `name` against the other's `alias` counts). A weak
    alias (a nickname) counts only when it equals a name outright, as
    `weak-exact`, and decide() never merges on that alone: a nickname that is
    one word of someone's name says next to nothing. Strongest first."""
    out = set()
    for x, weak_x in names_a:
        for y, weak_y in names_b:
            cmp = types.compare_name(x, y)
            if cmp.signal is not types.Signal.MATCH:
                continue
            if weak_x or weak_y:
                if cmp.how == "exact":
                    out.add("weak-exact")
            else:
                out.add(cmp.how)
    return sorted(out, key=_NAME_RANK.get)


def is_hard(hows: list[str]) -> bool:
    return "entity-exact" in hows or any(h.startswith("hard-") for h in hows)


def _soft_exact(hows: list[str]) -> list[str]:
    """`["address", ...]` for every soft exact match, as `address match`."""
    return [h.split(":", 1)[1] for h in hows if h.startswith("soft-exact")]


def _named(rec: dict, pcs: dict) -> bool:
    """Does this record carry any name-typed match value at all?"""
    return any(pcs.get(p) and pcs[p].match and pcs[p].ftm_type == "name" and vals
               for p, vals in (rec.get("properties") or {}).items())


def decide(rec_a: dict, rec_b: dict, pcs: dict, resolved: dict):
    """One candidate pair -> (status, criteria, match_hows), or None when
    nothing matched (a pair that only shared a candidate word is no pair, even
    when a distinct field differs). The rules are the whole of Layer 4's
    decision: a match with a distinct conflict is only proposed; a hard identifier or exact name merges; a soft
    exact match alone (address, date) is proposed unless there is nothing else
    to go on; weaker matches are proposed."""
    sp = specific(rec_a["schema"], rec_b["schema"])
    conflict, match_hows, _clashes = compare_detail(rec_a, rec_b, pcs[sp], resolved)
    if not match_hows:
        return None             # shared a candidate word, agreed on nothing: not a pair
    if conflict:
        status, criteria = "proposed", "distinct field conflict"
    elif is_hard(match_hows) or "exact" in match_hows:
        status, criteria = "auto", "exact match, no conflict"
    elif _soft_exact(match_hows) and not (
            _named(rec_a, pcs[rec_a["schema"]]) or _named(rec_b, pcs[rec_b["schema"]])):
        status, criteria = "auto", "exact match, no conflict"   # nothing else to go on
    elif _soft_exact(match_hows):
        both = _named(rec_a, pcs[rec_a["schema"]]) and _named(rec_b, pcs[rec_b["schema"]])
        status = "proposed"
        criteria = (f"{_soft_exact(match_hows)[0]} match only, "
                    f"{'names differ' if both else 'one side unnamed'}")
    elif match_hows:
        status, criteria = "proposed", f"{match_hows[0]} match, no conflict"
    else:
        return None
    if rec_a["schema"] != rec_b["schema"]:
        criteria += f" (generic {_generic(rec_a['schema'], rec_b['schema'])} -> {sp})"
    return status, criteria, match_hows


def compat(a: str, b: str) -> bool:
    """Two records may be the same entity only if one's schema is the other's
    ancestor (or they're equal): a generic `LegalEntity` can be a `Person`, a
    `Person` and a `Company` can never be each other."""
    return a == b or schema.is_a(a, b) or schema.is_a(b, a)


def depth(s: str) -> int:
    return len(schema.ancestors(s))


def specific(a: str, b: str) -> str:
    return a if (a == b or schema.is_a(a, b)) else b


def _generic(a: str, b: str) -> str:
    return b if specific(a, b) == a else a


def most_specific(schemas) -> str | None:
    """The one schema every other is an ancestor-or-equal of, else None."""
    for s in sorted(schemas):
        if all(schema.is_a(s, x) for x in schemas):
            return s
    return None


def chain_ok(schemas) -> bool:
    return most_specific(schemas) is not None


def guard_kinds(rows: list[dict], by_id: dict) -> None:
    """Never let a merge group span incompatible kinds.
    1. A record whose auto-matches span two incompatible kinds (a generic
       "Acme" matching both a Company and a Person) is a FORK: every one of
       its auto rows drops to `proposed` so a human picks (group cascade).
    2. A transitive join of incompatible kinds through other links is
       blocked: an auto row becomes `proposed`; an explicit `confirmed` row
       becomes `conflict` (surfaced, never silently overridden)."""
    partners: dict[str, set[str]] = {}
    for e in rows:
        if e["status"] == "auto":
            sa, sb = by_id[e["a"]]["schema"], by_id[e["b"]]["schema"]
            partners.setdefault(e["a"], {sa}).add(sb)
            partners.setdefault(e["b"], {sb}).add(sa)
    forks = {rid for rid, ss in partners.items() if not chain_ok(ss)}
    for e in rows:
        if e["status"] == "auto" and (e["a"] in forks or e["b"] in forks):
            e["status"] = "proposed"
            e["criteria"] += " (generic matches several kinds)"
    parent: dict[str, str] = {}
    schemas: dict[str, set[str]] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        schemas.setdefault(x, {by_id[x]["schema"]})
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in sorted((r for r in rows if r["status"] in ("auto", "confirmed")), key=lambda r: r["id"]):
        ra, rb = find(e["a"]), find(e["b"])
        if ra == rb:
            continue
        combined = schemas[ra] | schemas[rb]
        if chain_ok(combined):
            parent[rb] = ra
            schemas[ra] = combined
        elif e["status"] == "auto":
            e["status"] = "proposed"
            e["criteria"] += " (would join incompatible kinds)"
        else:
            e["status"], e["criteria"] = "conflict", e["criteria"] + " (confirmed link would join incompatible kinds)"
