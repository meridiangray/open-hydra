"""visuals.py — the drawn parts of a page: a life bar, an ancestors chart, navigation boxes.

Same rules as views.py: they draw only what the records say. A bar's ends are the
recorded birth and death (else the first and last dated record, and the caption says
so); a term with no end is drawn open, one with no start as a tick; an ancestor nobody
recorded is left blank. They take the same (page, Ctx) and return HTML or "".

    lifebar     a body section        a person's life as a bar, each dated term a bar under it
    ancestors   a body section        parents, grandparents, great-grandparents as a chart
    navboxes    the foot of the page  holders of the person's posts, their house, universe collections
"""
from __future__ import annotations

import html

from hydra.wiki import views
from hydra.wiki.views import year

e = html.escape

LANE, GAP, TOP, W, PAD = 16, 4, 22, 800, 10
CHAR = 6.3                                    # an estimate of a 11px glyph's width, for fitting labels
LABEL_MAX = 48
OPEN_MIN = 14                                 # the least width of a term with no end recorded


def _scale(lo: int, hi: int) -> list[int]:
    """Years to label: round steps, at most about eight of them."""
    span = max(hi - lo, 1)
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200) if span / s <= 8)
    return list(range(-(-lo // step) * step, hi + 1, step))


def lifebar(p, c: views.Ctx) -> str:
    if p["schema"] != c.reg.roles.PERSON:
        return ""
    terms = []
    for r in views._offices(p, c):
        s, t = year(r.get("startDate") or r.get("date")), year(r.get("endDate"))
        if s or t:
            terms.append((s, t, r))
    if not terms:
        return ""
    born, died = year(c.first(p["body"], "birthDate")), year(c.first(p["body"], "deathDate"))
    seen = [y for s, t, _ in terms for y in (s, t) if y]
    lo, hi = born or min(seen + ([died] if died else [])), died or max(seen + ([born] if born else []))
    if hi <= lo:
        hi = lo + 1
    x = lambda y: PAD + (y - lo) / (hi - lo) * (W - 2 * PAD)

    lanes: list[float] = []                     # the right edge of the last bar in each lane
    placed = []
    for s, t, r in sorted(terms, key=lambda m: (m[0] or m[1], m[1] or hi)):
        a, b = x(s if s else t), x(t if t else hi)
        if s and not t:                         # open: never thinner than a stub, and kept inside the frame
            b = max(b, a + OPEN_MIN)
            a, b = a - max(0, b - (W - PAD)), min(b, W - PAD)
        elif s and t:
            b = max(b, a + 3)
        lane = next((i for i, edge in enumerate(lanes) if edge + 3 <= a), None)
        if lane is None:
            lanes.append(0)
            lane = len(lanes) - 1
        lanes[lane] = max(b, a + 3)
        placed.append((lane, s, t, r, a, b))

    h = TOP + len(lanes) * (LANE + GAP) + GAP
    svg = [f"<svg class=lifebar viewBox='0 0 {W} {h}' role=img width='100%' "
           f"aria-label='{e(p['title'])}: life and offices, {lo} to {hi}'>"]
    for y in _scale(lo, hi):
        svg.append(f"<line class=lb-grid x1='{x(y):.1f}' x2='{x(y):.1f}' y1='{TOP - 4}' y2='{h}'/>"
                   f"<text class=lb-axis x='{x(y):.1f}' y='10' text-anchor=middle>{y}</text>")
    svg.append(f"<rect class=lb-life x='{x(born or lo):.1f}' y='{TOP - 8}' width='{x(died or hi) - x(born or lo):.1f}' "
               f"height='5' rx='2'><title>{e(c.life(p['body']) or f'recorded {lo}–{hi}')}</title></rect>")
    for lane, s, t, r, a, b in placed:
        y0 = TOP + lane * (LANE + GAP)
        when = views.span(r.get("startDate") or r.get("date"), r.get("endDate"))
        tip = f"{c.wiki.title(r, qualified=False)}, {when}" + ("" if s else " (start not recorded)") + \
              ("" if t or not s else " (no end recorded)")
        label = c.wiki.title(r, qualified=False)
        room = int((b - a - 8) / CHAR)
        text = "" if room < 5 else (label if len(label) <= min(room, LABEL_MAX) else label[:min(room, LABEL_MAX) - 1] + "…")
        cls = "lb-term" + ("" if s and t else " lb-open" if s else " lb-tick")
        if not s:                               # an end with no start: a tick, not a span
            a, b = b - 3, b
        shape = f"<rect class='{cls}' x='{a:.1f}' y='{y0}' width='{b - a:.1f}' height='{LANE}' rx='3'/>"
        txt = f"<text class=lb-label x='{a + 4:.1f}' y='{y0 + 12}'>{e(text)}</text>" if text and s else ""
        link = c.L.page(r["other"]) if r.get("other") else ""
        body = f"<title>{e(tip)}</title>{shape}{txt}"
        svg.append(f"<a href='{e(link)}'>{body}</a>" if link else f"<g>{body}</g>")
    svg.append("</svg>")
    missing = " or ".join(w for w, v in (("birth", born), ("death", died)) if not v)
    note = f" No {missing} is recorded, so the scale ends at the nearest dated record." if missing else ""
    return (f"<figure class=lifebarbox>{''.join(svg)}"
            f"<figcaption class=meta>Offices by year{e(' (' + c.life(p['body']) + ')') if c.life(p['body']) else ''}.{e(note)}"
            f"{views.info('Hatched: no end date. Tick: no start date.')}</figcaption></figure>")


# ---------------------------------------------------------------------------- ancestors

def _ancestors(p, c: views.Ctx, depth: int) -> list[list]:
    """levels[k] = 2**k slots, father before mother: a {body|name, rel} or None. A cycle stops at
    the person it comes back to."""
    levels = [[(p["body"], p, {p["body"]})]]
    for _ in range(depth):
        nxt = []
        for node in levels[-1]:
            pars = c.parents(node[1]) if node and node[1] else {}
            for k in ("father", "mother"):
                r = pars.get(k)
                if not r or (r.get("other") and r["other"] in node[2]):
                    nxt.append(None)
                    continue
                page = c.page(r.get("other"))
                nxt.append((r.get("other") or r.get("name"), page, node[2] | {r.get("other")}, r))
        levels.append(nxt)
    return levels


def ancestors(p, c: views.Ctx) -> str:
    if p["schema"] != c.reg.roles.PERSON:
        return ""
    levels = _ancestors(p, c, 3)
    deep = max((k for k, lv in enumerate(levels) if any(lv)), default=0)
    if deep < 2:                                # parents alone are already in Family
        return ""
    G, rows = deep, 2 ** deep
    cells = []
    for k in range(G + 1):
        span = 2 ** (G - k)
        for i, node in enumerate(levels[k]):
            if not node:
                continue
            body, page = node[0], node[1]
            label = f"<a href='{c.L.page(body)}'>{e(c.wiki.title(body, qualified=False))}</a>" if page else e(str(body))
            life = c.life(body) if page else ""
            cells.append(f"<div class='anc{' self' if k == 0 else ''}' style='grid-column:{k + 1};"
                         f"grid-row:{i * span + 1}/span {span}'>"
                         f"{'<b>' + label + '</b>' if k == 0 else label}"
                         f"{'<div class=meta>' + e(life) + '</div>' if life else ''}</div>")
    return (f"<h2 id=ancestors>Ancestors{views.info('Three generations, from recorded parents.')}</h2>"
            f"<div class=ancwrap><div class=ancestors style='grid-template-columns:repeat({G + 1},minmax(9rem,1fr));"
            f"grid-template-rows:repeat({rows},auto)'>{''.join(cells)}</div></div>")


# ---------------------------------------------------------------------------- navboxes

BOX_CAP, OPEN_MAX, MAX_POSTS = 200, 12, 4


def _box(title_html: str, members: list[str], me: str, c: views.Ctx, note: str = "") -> str:
    shown = members[:BOX_CAP]
    items = " · ".join(f"<b>{e(c.wiki.title(b))}</b>" if b == me else c.a(b) for b in shown)
    more = f" <span class=meta>and {len(members) - len(shown)} more</span>" if len(members) > len(shown) else ""
    return (f"<details class=navbox{' open' if len(members) <= OPEN_MAX else ''}>"
            f"<summary>{title_html} <span class=meta>({len(members)})</span></summary>"
            f"<div class=navlist>{items}{more}{note}</div></details>")


def navboxes(p, c: views.Ctx) -> str:
    """The foot boxes, as Wikipedia's navboxes: each lists the others in a group, the page bolded."""
    out, me = [], p["body"]
    if p["schema"] == c.reg.roles.PERSON:
        posts = list(dict.fromkeys(r["other"] for r in views._offices(p, c) if r.get("other") in c.wiki.pages))
        for post in posts[:MAX_POSTS]:
            holders = list(dict.fromkeys(r["other"] for r in c.holders(post) if r.get("other") in c.wiki.pages))
            if len(holders) >= 3:
                out.append(_box(f"Holders of {c.a(post)}", holders, me, c,
                                "<div class=meta>by first term</div>"))
    for _, g, org, _ in views.groups_of(p, c):      # groups.yaml: the group's other members
        box = g.get("box") or {}
        members = c.wiki.cats.get(("group", views.group_category(g, c, org)), set())
        if box is not False and len(members) >= int(box.get("min", 3)):
            by_birth = box.get("order", "birth") == "birth"
            ordered = sorted(members, key=(lambda b: (year(c.first(b, "birthDate")) or 99999, c.wiki.title(b)))
                             if by_birth else c.wiki.title)
            out.append(_box(c.a(org), ordered, me, c, "<div class=meta>by year of birth</div>" if by_birth else ""))
    for coll in p["collections"]:
        members = c.wiki.cats.get(("universe", coll), set())
        if len(members) >= 3:
            out.append(_box(e(c.wiki.cat_label("universe", coll)), sorted(members, key=c.wiki.title), me, c))
    return f"<div class=navboxes>{''.join(out)}</div>" if out else ""


views.SECTIONS.update(lifebar=lifebar, ancestors=ancestors)
