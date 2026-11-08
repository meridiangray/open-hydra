"""pages.py — one page per live H, from the members and the identity: what a wiki shows.

A page holds only what the records say, each value with the records that
supplied it (its footnotes). What the archive's own rule files decide comes
along: captions (pins), images and badges (hints.yaml), the parent chain (the
tree), the post's rank (positions.yaml), and which properties tell two
same-named entities apart (the `distinct` lists, for qualifiers).

    title       archive caption pin > universe pin (cap-<body>) > the anchor's caption
    qualifier   only when two pages share a title: born/died years, a parent, else the first
                distinct property whose values differ ("Saud bin Abdulaziz (born 1748)")
    relations   every edge either end of which is the page, both directions; an end that
                names no record is a red link (a stub) or an unresolved name, never dropped.
                A relationship's other links (its deal in `transaction`, a payment's
                `contract`...: any entity property besides its two ends) are its context:
                kept as an H under the property's name, or listed in `context` as red or
                unresolved, never dropped either
"""
from __future__ import annotations

import re
from collections import defaultdict

from hydra import dates, kinship, layout
from hydra import keys as hkeys
from hydra.cli import export as hexport
from hydra.identity import classify
from hydra.identity import types as htypes
from hydra.universe import hid, identity, layer, table

NAME_PROPS = ("name", "alias", "weakAlias", "previousName")
SKIP_PROPS = {"name", "notes", "description", "sources", "proof", "upstream", "summary"}
DETAIL_PROPS = ("relationship", "role", "startDate", "endDate", "date",
                "percentage", "status", "capacity", "amount", "currency")
URL = re.compile(r"https?://[^\s\]\)>,]+")


def _rank_depth(positions: dict, name: str | None) -> int | None:
    """How far below the top of the ladder a position is (0: nothing above it)."""
    if not name or name not in positions:
        return None
    depth, cur, seen = 0, name, set()
    while (positions.get(cur) or {}).get("uppers") and cur not in seen:
        seen.add(cur)
        cur = sorted(positions[cur]["uppers"])[0]
        depth += 1
    return depth


def titles_of(I: identity.Identity, pins: dict) -> tuple[dict, dict]:
    """-> ({body: title}, {body: schema}) for every live H."""
    titles, schema_of = {}, {}
    for body, h in I.hs.items():
        c = h["cluster"]
        if c is None:
            continue
        cands = [I.ents[er] for er in I.clusters[c]]
        schema_of[body] = max((e["schema"] for _, e in cands), key=lambda s: (len(I.anc.get(s, ())), s))
        pinned = next((m.nodes[e["id"]]["caption"] for m, e in cands if e["id"] in m.pinned and e["id"] in m.nodes), None)
        am, ae = I.ents[I.ent_of_record[I.anchor_of[c]]]
        default = (am.nodes.get(ae["id"]) or {}).get("caption") or hexport._caption(ae)
        titles[body] = pinned or pins.get(body) or default
    return titles, schema_of


def build_pages(root, I: identity.Identity, pins: dict, ucolls: dict) -> tuple[list, list, dict, dict]:
    """-> (pages, media [(source file, rel)], titles {body: title}, schema_of {body: schema})."""
    live = [m for m in I.members if not m.problem]
    by_name = {m.name: m for m in live}
    titles, schema_of = titles_of(I, pins)

    claims_by = {m.name: defaultdict(list) for m in live}
    for m in live:
        for row in m.claims:
            claims_by[m.name][(row["entity"], row["prop"])].append(row)

    def doc_caption(m, rec, v: str):
        sid = (((rec or {}).get("_id_links") or {}).get("sources") or {}).get(v) \
            or m.records.get(v) or next((i for i in m.entities if i.endswith(":" + v)), None)
        e = m.entities.get(sid) if sid else None
        return (hexport._caption(e), I.link(m, sid)) if e else (v, None)

    def end(m, value: str) -> dict:
        """One end of an edge: an H; a name that names several records (unresolved: a review
        question); or a name that names none (a red link: a record nobody has written yet)."""
        b = I.link(m, value)
        if b:
            return {"other": b}
        sid = m.records.get(value, value)
        name = m.stubs.get(sid) or value
        if value in m.ambiguous:
            return {"other": None, "name": name, "unresolved": True}
        return {"other": None, "name": name, "red": True}

    names_index = defaultdict(set)
    for body, h in I.hs.items():
        if h["cluster"] is None:
            continue
        for er in I.clusters[h["cluster"]]:
            for p in NAME_PROPS:
                for v in I.ents[er][1]["properties"].get(p) or []:
                    names_index[htypes.norm_text(v)].add(body)
        names_index[htypes.norm_text(titles[body])].add(body)
    not_pairs = set()
    for body, row in I.rows.items():
        for o in row.get("not") or []:
            not_pairs.add(frozenset((table.follow(I.rows, body), table.follow(I.rows, o))))
    for m in live:                          # a member's own review said "two entities": as decided as a `not`
        for pair in m.apart:
            bs = {I.body_of_record(m.ref(rid)) for rid in pair}
            if len(bs) == 2 and None not in bs:
                not_pairs.add(frozenset(bs))

    def context_props(m, sname: str, edge: dict) -> list[str]:
        """A relationship's links besides its two ends: `transaction`, a payment's `contract`..."""
        return [p for p, d in m.schemas[sname]["props"].items()
                if d.get("type") == "entity" and p not in (edge["source"], edge["target"]) and p not in SKIP_PROPS]

    def context_of(m, value: str) -> dict:
        """One context link: as an edge's end resolves it, else by a name exactly one entry has
        anywhere in the universe; a name several have is unresolved, one none has is red."""
        hit = end(m, value)
        if hit.get("other") or hit.get("unresolved"):
            return hit
        named = names_index.get(htypes.norm_text(value)) or ()
        if len(named) == 1:
            return {"other": next(iter(named))}
        return {"other": None, "name": hit["name"], "unresolved": True} if named else hit

    relations = defaultdict(list)
    for m in live:
        for sid, e in m.entities.items():
            edge = (m.schemas.get(e["schema"]) or {}).get("edge")
            if not edge:
                continue
            props = e["properties"]
            plabels = m.schemas[e["schema"]]["props"]
            detail = {p: props[p][0] for p in DETAIL_PROPS if props.get(p)}
            for p in ("startDate", "endDate", "date"):          # "c. 1748": the qualifier its record kept
                if not detail.get(p):
                    continue
                kind = next((a[p] for x, s in m.records.items() if s == sid
                             for a in [((m.raw.get(x) or {}).get("_meta") or {}).get("approx") or {}] if a.get(p)), None)
                if kind:
                    detail.setdefault("approx", {})[p] = kind
            for p in context_props(m, e["schema"], edge):
                for v in props.get(p) or []:
                    c = context_of(m, v)
                    if c.get("other"):
                        detail.setdefault(p, c["other"])          # the first that resolves: the page links it
                        every = detail.setdefault("links", {}).setdefault(p, [])
                        if c["other"] not in every:               # and every one (a stake bought in one deal, sold in another)
                            every.append(c["other"])
                    else:
                        detail.setdefault("context", []).append(
                            {"prop": p, "label": (plabels.get(p) or {}).get("label", p), "name": c["name"],
                             **({"unresolved": True} if c.get("unresolved") else {"red": True})})
            extra = {"edge": e["schema"], "notes": props.get("notes") or [],
                     "urls": sorted(set(props.get("publisherUrl") or []) | set(props.get("sourceUrl") or []))}
            cite = {"member": m.name, "entity": sid}
            section = m.schemas[e["schema"]]["label"]
            rel = detail.get("relationship")
            for s in props.get(edge["source"]) or []:
                for t in props.get(edge["target"]) or []:
                    es, et = end(m, s), end(m, t)
                    if es.get("other") and es["other"] == et.get("other"):
                        continue
                    if es.get("other"):
                        relations[es["other"]].append({
                            "section": section, "side": "source", **et, **detail, **extra, "cite": cite,
                            "verb": rel or (plabels.get(edge["target"]) or {}).get("label", edge["target"])})
                    if et.get("other"):
                        relations[et["other"]].append({
                            "section": section, "side": "target", **es, **detail, **extra, "cite": cite,
                            "verb": f"{rel} of" if rel else (plabels.get(edge["source"]) or {}).get("label", edge["source"])})

    pages, media_out = [], []
    for body, h in sorted(I.hs.items()):
        c = h["cluster"]
        if c is None:
            continue
        cites: dict[tuple, int] = {}
        cite_rows = []

        def cite(member: str, entity: str, record: str | None = None) -> list[int]:
            m = by_name[member]
            recs = [record] if record else sorted(r for r, s in m.records.items() if s == entity) or [entity]
            out = []
            for r in recs:
                key = (member, r)
                if key not in cites:
                    raw = (m.raw.get(r) or {}).get("properties") or {}
                    docs = [doc_caption(m, m.raw.get(r), v) for v in raw.get("sources") or []]
                    notes = "\n".join(raw.get("notes") or [])
                    cites[key] = len(cites) + 1
                    cite_rows.append({"n": cites[key], "member": member, "record": r,
                                      "schema": (m.raw.get(r) or {}).get("schema", ""),
                                      "collection": (m.raw.get(r) or {}).get("_collection", ""),
                                      "docs": [{"title": t, "h": b} for t, b in docs], "quote": notes,
                                      "urls": sorted(set(raw.get("publisherUrl") or []) | set(raw.get("sourceUrl") or [])
                                                     | set(URL.findall(notes)))})
                out.append(cites[key])
            return out

        infobox: dict[str, dict] = {}
        aliases, leads, notes, images, datasets, upstream = set(), [], [], [], set(), set()
        badges, badge, rank = [], None, None
        for er in sorted(I.clusters[c]):
            m, e = I.ents[er]
            pdefs = m.schemas.get(e["schema"], {}).get("props", {})
            datasets.update(f"{m.name}/{d}" for d in e.get("datasets") or [])
            for p in NAME_PROPS:
                aliases.update(e["properties"].get(p) or [])
            leads += [v for p in ("description", "summary") for v in e["properties"].get(p) or [] if v not in leads]
            notes += [v for v in e["properties"].get("notes") or [] if v not in notes]
            for rid, s in m.records.items():
                if s == e["id"]:
                    upstream.update((m.raw.get(rid, {}).get("properties") or {}).get("upstream") or [])
            node = m.nodes.get(e["id"]) or {}
            badges += [b for b in node.get("badges") or [] if b not in badges]
            badge = badge or node.get("badge")
            if rank is None and node.get("position"):
                rank = {"name": node["position"], "depth": _rank_depth(m.positions, node["position"]),
                        "tier": node.get("tier")}
            for kind in layer.IMAGE_KINDS:
                for img in node.get(kind) or []:
                    src = next((m.root / d / img["path"] for d in layer.IMAGE_DIRS
                                if (m.root / d / img["path"]).is_file()), None)
                    if src:
                        rel = f"media/{m.name}/{img['path']}"
                        media_out.append((src, rel))
                        if (kind, rel) not in [(k, x) for k, x in images]:
                            images.append((kind, rel))
            for p, vals in e["properties"].items():
                d = pdefs.get(p) or {}
                if p in SKIP_PROPS or p in NAME_PROPS or d.get("hidden"):
                    continue
                box = infobox.setdefault(p, {"prop": p, "label": d.get("label") or p, "type": d.get("type"), "values": {}})
                for v in vals:
                    target = I.link(m, v) if d.get("type") == "entity" else None
                    if d.get("type") == "entity" and not target:
                        sid = m.records.get(v, v)
                        if sid in m.entities and (m.schemas.get(m.entities[sid]["schema"]) or {}).get("edge"):
                            continue             # an edge: shown under relations
                        shown = {"value": m.stubs.get(sid, v), "h": None,
                                 "red": v not in m.ambiguous, "unresolved": v in m.ambiguous}
                    else:
                        shown = {"value": v if not target else None, "h": target}
                    rowcl = claims_by[m.name].get((e["id"], p)) or []
                    recs = sorted({x["record"] for x in rowcl if target or x["value"] == v})
                    if d.get("type") == "date":         # "c. 1748": the qualifier its record kept
                        kind = next((((m.raw.get(x) or {}).get("_meta") or {}).get("approx", {}).get(p)
                                     for x in recs if (((m.raw.get(x) or {}).get("_meta") or {}).get("approx") or {}).get(p)),
                                    None)
                        if kind:
                            shown["approx"] = kind
                            shown["edtf"] = dates.edtf(v, kind)      # the same, as ISO 8601-2 says it
                    val = box["values"].setdefault(target or shown["value"], {**shown, "cites": set()})
                    for r in recs or [None]:
                        val["cites"].update(cite(m.name, e["id"], r))
        featured = []
        for er in I.clusters[c]:
            m, e = I.ents[er]
            featured += [p for p in m.schemas.get(e["schema"], {}).get("featured", []) if p not in featured]
        box_rows = sorted((b for b in infobox.values() if b["values"]),
                          key=lambda b: (b["prop"] not in featured,
                                         featured.index(b["prop"]) if b["prop"] in featured else 0, b["label"]))
        for b in box_rows:
            b["values"] = [{**v, "cites": sorted(v["cites"])} for v in b["values"].values()]
        rels = []
        for r in relations.get(body, []):
            r = dict(r)
            r["cites"] = cite(r["cite"]["member"], r["cite"]["entity"])
            del r["cite"]
            rels.append(r)
        rels.sort(key=lambda r: (r["section"], r["verb"], r.get("startDate", ""),
                                 titles.get(r.get("other"), r.get("name", ""))))
        am, ae = I.ents[I.ent_of_record[I.anchor_of[c]]]
        crumbs, pid, guard = [], (am.nodes.get(ae["id"]) or {}).get("pid"), 0
        while pid and guard < 8:
            b = I.link(am, pid)
            if not b or b == body or b in crumbs:
                break
            crumbs.insert(0, b)
            pid, guard = (am.nodes.get(pid) or {}).get("pid"), guard + 1
        also = set()
        for a in aliases | {titles[body]}:
            also |= names_index[htypes.norm_text(a)]
        also = sorted(b for b in also - {body} if b in schema_of
                      and identity.compatible(schema_of[b], schema_of[body], I.anc)
                      and frozenset((body, b)) not in not_pairs)
        aliases.discard(titles[body])
        if rank is None and schema_of[body] == "Position":     # a post's rank: its title on the ladder
            from hydra.shape.rules import canonical
            ladder = am.positions
            name = next((canonical(t, ladder) for t in [titles[body], *sorted(aliases)] if canonical(t, ladder)), None)
            if name:
                rank = {"name": name, "depth": _rank_depth(ladder, name), "tier": None}
        flags = hid.flag_value(h["flags"])
        src_colls = set()                                  # the collection files the page's records came from
        for rid in I.cl_records[c]:
            er = I.ent_of_record.get(rid)
            if er not in I.ents:
                continue
            rm = I.ents[er][0].raw.get(rid.split("/", 1)[-1])
            if (rm or {}).get("_collection"):
                src_colls.add(rm["_collection"])
        pages.append({
            "h": hid.fmt(body, h["state"], flags), "body": body, "state": h["state"],
            "collection": sorted(src_colls),
            "flags": hid.flag_names(flags), "disagree": h.get("disagree", []),
            "title": titles[body], "qualifier": "", "schema": schema_of[body], "aliases": sorted(aliases),
            "lead": leads, "notes": notes, "infobox": box_rows, "relations": rels, "parents": crumbs,
            "images": [rel for _, rel in sorted(images, key=lambda x: layer.IMAGE_KINDS.index(x[0]))],
            "media": [{"kind": layer.IMAGE_KINDS_ONE[k], "path": rel}
                      for k, rel in sorted(images, key=lambda x: layer.IMAGE_KINDS.index(x[0]))],
            "badge": badge, "badges": badges, "rank": rank, "also": also, "citations": cite_rows,
            "members": I.cl_records[c], "datasets": sorted(datasets), "upstream": sorted(upstream),
            "keys": [hkeys.describe(I.keyconf, k) for k in sorted(
                I.keys.get(c, ()), key=lambda k: (k != h.get("key"), hkeys.rank(I.keyconf, k.split(":", 1)[0]), k))],
            "collections": sorted(k for k, v in ucolls.items() if body in v["members"]),
        })
    _qualify(pages, I, by_name, kinship.load(root))
    return pages, media_out, titles, schema_of


def _distinct_props(I, by_name, er) -> list[str]:
    m, e = I.ents[er]
    params = m.root / layout.PARAMS_DIR if m.root and (m.root / layout.PARAMS_DIR).is_dir() else None
    pcs = classify.classify(e["schema"], params) if e["schema"] in m.schemas else {}
    return [p for p, pc in pcs.items() if pc.distinct]


def _qualify(pages: list, I, by_name, kin=None) -> None:
    """Pages that share a title get a short qualifier, from what tells them apart."""
    kin = kin or kinship.load(None)
    by_title = defaultdict(list)
    for p in pages:
        by_title[(htypes.norm_text(p["title"]), p["schema"])].append(p)
    page_of = {p["body"]: p for p in pages}
    year = lambda p, prop: next((dates.year(v["value"]) for b in p["infobox"] if b["prop"] == prop
                                 for v in b["values"] if dates.year(v["value"] or "")), None)
    for group in by_title.values():
        if len(group) < 2:
            continue
        for p in group:
            born, died = year(p, "birthDate"), year(p, "deathDate")
            q = f"{born}–{died}" if born and died else f"born {born}" if born else f"died {died}" if died else ""
            if not q:                              # the words are kinship.yaml's
                parent = next((r for r in p["relations"] if r.get("edge") == "Family" and r.get("side") == "source"
                               and kin.is_(r["verb"], "parent") and r.get("other")), None)
                if parent:
                    q = f"{kin.name('child', _gender(p))} of " \
                        f"{page_of[parent['other']]['title'] if parent['other'] in page_of else parent['other']}"
            if not q:
                kids = [r for r in p["relations"] if r.get("edge") == "Family" and r.get("side") == "target"
                        and str(r["verb"]).endswith(" of") and kin.is_(r["verb"], "parent") and r.get("other") in page_of]
                if kids:
                    q = f"{kin.base(kids[0]['verb'])} of {page_of[kids[0]['other']]['title']}"
            if not q:
                er = I.ent_of_record.get(p["members"][0])
                for prop in (_distinct_props(I, by_name, er) if er else []):
                    vals = [v["value"] for b in p["infobox"] if b["prop"] == prop for v in b["values"] if v.get("value")]
                    others = {v["value"] for o in group if o is not p for b in o["infobox"] if b["prop"] == prop
                              for v in b["values"] if v.get("value")}
                    if vals and vals[0] not in others:
                        q = vals[0]
                        break
            p["qualifier"] = q


def _gender(p) -> str:
    return next((v["value"] for b in p["infobox"] if b["prop"] == "gender" for v in b["values"]), "")
