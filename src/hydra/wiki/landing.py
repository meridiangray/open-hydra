"""landing.py — the sections of the main page, each a small function of (wiki, links).

Each reads what the wiki already has (pages, the years index, the history log, the readiness
findings) and returns HTML or "". `wiki.yaml` `landing:` lists the ones to show, in order.

    domains     a card per kind of entry, with its icon and count          schemas
    featured    one entry, chosen by the day                               pages with the most recorded
    added       the entries the latest changes brought in                  history.describe
    recent      the last changes, what each did, a link to review it       history.describe
    explore     a row of portals: each kind of entry and how many           schemas, groups, the years index
    current     posts whose last term is open, and who holds them          Occupancy
    in_office   the same, the six latest appointments (the main page)      Occupancy
    years_ago   what happened 25, 50, 100... years before this year        the years index
    deals       the latest dated deals, with their price                   Event
    groups      the groups (houses, parties) and their sizes               groups.yaml
    decades     births, deaths and office changes by decade, as bars       the years index
    attention   what keeps pages from being complete                       readiness.check
"""
from __future__ import annotations

import html
import re
from collections import Counter
from datetime import date

from hydra import history
from hydra.wiki import icons, readiness, views
from hydra.wiki.views import year

e = html.escape

ORDER = ("explore", "featured", "in_office", "years_ago", "added", "people")   # the main page: a way in, not an inventory
BROWSE = ("domains", "groups", "current", "deals", "decades")      # /browse: what the archive holds
MAINTENANCE = ("attention", "recent")                              # /maintenance: what needs doing


ASSETS = ("RealEstate", "Vessel", "Airplane", "Vehicle", "Asset", "Security")


def hero(w, L) -> str:
    """The welcome: the archive's name, wiki.yaml `about:` when given, the figures, a search box."""
    shown = [w.pages[b] for b in w.listed]
    about = str((w.conf or {}).get("about") or "").strip()
    sourced = sum(1 for p in shown if any(c["docs"] or c["urls"] for c in p["citations"]))
    last = (changes(w, 1) or [None])[0]
    day = e(views.long_date(last["time"][:10])) if last else ""
    when = (f"<span>Updated <a href='{L.change(last['sid'])}'>{day}</a></span>"
            if last and L.change(last["sid"]) else (f"<span>Updated {day}</span>" if last else ""))
    return (f"<section class='hero front'><h1>Welcome to {e(w.report['title'])}</h1>"
            + (f"<p class=about>{e(about)}</p>" if about else "")
            + f"<p class=figures><span><b>{len(shown):,}</b> entries</span><span><b>{sourced:,}</b> with sources</span>{when}</p>"
            f"<form action='{L.search()}' role=search><input name=q type=search placeholder='Search {len(shown):,} entries' "
            f"aria-label=Search></form></section>")


def explore(w, L) -> str:
    """Ways in, as a row of portals: each kind of thing the archive holds, and how many."""
    types = Counter(w.pages[b]["schema"] for b in w.listed)
    years = sorted(w.years) if w.years else []
    orgs = types.get("Company", 0) + types.get("PublicBody", 0) + types.get("Organization", 0)
    groups_n = len({k for (kind, k) in w.cats if kind == "group"})
    group_label = next((g.get("label") for g in w.groups.values() if g.get("label")), "Group")
    browse = "/browse" if not L.static else L.home()
    portals = [
        ("user", "People", types.get("Person", 0), L.cat("type", "Person")),
        ("briefcase", "Offices", types.get("Position", 0), L.cat("type", "Position")),
        ("building", "Organizations", orgs, browse),
        ("gem", "Property", sum(types.get(s, 0) for s in ASSETS), browse),
        ("calendar", "Deals", types.get("Event", 0), L.cat("type", "Event")),
        ("users", f"{group_label}s", groups_n, "/groups" if not L.static else L.home()),
        ("calendar", "Timeline", f"{years[0]}–{years[-1]}" if years else "", L.years()),
    ]
    show = lambda n: f"{n:,}" if isinstance(n, int) else e(str(n))
    items = "".join(f"<a class=portal href='{e(href)}'><span class=ic>{icons.svg(w.root, ic, 16)}</span>"
                    f"<span class=pt>{e(title)}</span><b>{show(n)}</b></a>" for ic, title, n, href in portals if n)
    return f"<nav class='wide portals' aria-label='Browse by kind'>{items}</nav>"


def years_ago(w, L) -> str:
    """Round anniversaries: what the record has for 25, 50, 100... years before this one."""
    if not w.years:
        return ""
    now = date.today().year
    rows = []
    for ago in (25, 50, 75, 100, 125, 150, 200, 250, 300):
        y, n = now - ago, 0
        for kind, b, post in sorted(w.years.get(y) or [], key=lambda x: ("took", "births", "deaths", "left").index(x[0])):
            if n == 2 or b not in w.listed or (kind in ("took", "left") and not post):
                continue
            where = (w.a(L, post) if post in w.pages else e(str(post))) if post else ""
            what = {"births": "born", "deaths": "died", "took": f"took office as {where}",
                    "left": f"left office as {where}"}[kind]
            rows.append(f"<li><a class=yr href='{L.year(y)}'>{y}</a><span>{w.a(L, b)} {what}"
                        f" <span class=meta>· {ago} years ago</span></span></li>")
            n += 1
        if len(rows) >= 7:
            break
    if not rows:
        return ""
    return (f"<section class=panel><h2>Anniversaries</h2><ul class=ago>{''.join(rows)}</ul>"
            f"<p class=meta><a href='{L.years()}'>Browse all years →</a></p></section>")


def people(w, L) -> str:
    """Faces: the people with a portrait, the most recorded first."""
    def score(b):
        p = w.pages[b]
        return (len(views.Ctx(w, L, p).rels(p, w.reg_for(p).roles.TENURE, "source")), len(p["citations"]))
    faces = sorted((b for b in w.listed if views.image(w.pages[b]) and w.pages[b]["schema"] == w.reg_for(w.pages[b]).roles.PERSON),
                   key=lambda b: (-score(b)[0], -score(b)[1], w.title(b)))
    if len(faces) < 3:
        return ""
    c = views.Ctx(w, L, None)
    strip = "".join(f"<a href='{L.page(b)}'><img src='{L.asset(views.image(w.pages[b]))}' alt='' loading=lazy>"
                    f"<span>{e(w.title(b))}</span><span class=meta>{e(c.life(b))}</span></a>" for b in faces[:12])
    n = sum(1 for b in w.listed if w.pages[b]["schema"] == w.reg_for(w.pages[b]).roles.PERSON)
    return (f"<section class='wide panel people'><h2>People <a class=more href='{L.cat('type', 'Person')}'>See all {n:,} →</a></h2>"
            f"<div class=strip>{strip}</div></section>")


def domains(w, L) -> str:
    kinds = Counter(w.pages[b]["schema"] for b in w.listed)
    cards = "".join(
        f"<a class=card href='{L.cat('type', s)}'><span class=ic aria-hidden=true>{icons.for_schema(w.root, s, 18)}</span>"
        f"<span class=lbl>{e(w.type_label(s, plural=True))}</span><span class=count>{n:,}</span></a>"
        for s, n in kinds.most_common())
    return f"<nav class='wide domains' id=domains aria-label='Entry categories'>{cards}</nav>"


def _excerpt(w, L, p) -> str:
    """The lead's first paragraph, without its footnote marks (they point into another page)."""
    lead = views.lead(p, views.Ctx(w, L, p))
    m = re.search(r"<p>(.*?)</p>", lead, re.S)
    return re.sub(r"<sup>.*?</sup>", "", m.group(1)) if m else ""


def featured(w, L) -> str:
    def score(p) -> int:
        c = views.Ctx(w, L, p)
        return (3 if views.image(p) else 0) + min(len(c.rels(p, c.reg.roles.TENURE, "source")), 4) \
            + (1 if any(ci["docs"] or ci["urls"] for ci in p["citations"]) else 0) + (1 if p["lead"] else 0)
    people = [p for p in w.pages.values() if p["schema"] == w.reg_for(p).roles.PERSON
              and views.Ctx(w, L, p).rels(p, w.reg_for(p).roles.TENURE, "source")]
    if not people:
        return ""
    top = sorted(people, key=lambda p: (-score(p), p["title"]))[:30]
    p = top[date.today().toordinal() % len(top)]
    c = views.Ctx(w, L, p)
    img = f"<img src='{L.asset(views.image(p))}' alt=''>" if views.image(p) else ""
    life = c.life(p["body"])
    return (f"<section class=panel><h2>Featured entry</h2><div class='feat'>{img}<div>"
            f"<h3><a href='{L.page(p['body'])}'>{e(w.title(p['body']))}</a>"
            f"{' <span class=meta>(' + e(life) + ')</span>' if life else ''}</h3>"
            f"<p>{_excerpt(w, L, p)}</p><p><a href='{L.page(p['body'])}'>Read more →</a></p></div></div></section>")


def current(w, L, limit: int = 12, latest: bool = False) -> str:
    """Posts whose last term is open: a start, no end, no death recorded for the holder.
    `latest`: the most recent appointments first (the main page), else by office."""
    rows = []
    for b, p in w.pages.items():
        if p["schema"] != w.reg_for(p).roles.POST:
            continue
        c = views.Ctx(w, L, p)
        terms = c.holders(b)
        if terms and c.incumbent(terms[-1]):
            rows.append((w.title(b), b, terms[-1]))
    if not rows:
        return ""
    since = lambda t: year(t.get("startDate") or t.get("date")) or 0
    rows.sort(key=(lambda r: (-since(r[2]), r[0])) if latest else None)
    items = "".join(
        f"<tr><td>{w.a(L, b)}</td><td>{w.a(L, t)}</td>"
        f"<td class=meta>{since(t) or ''}</td></tr>" for _, b, t in rows[:limit])
    more = (f"<p class=meta><a href='/current'>All {len(rows)} →</a></p>" if latest and not L.static
            else f"<p class=meta>and {len(rows) - limit} more.</p>") if len(rows) > limit else ""
    return (f"<section class=panel id=current><h2>Officeholders"
            f" <span class=meta>({len(rows)})</span></h2>"
            f"<table class=list><tr><th>Office</th><th>Holder</th><th>Since</th></tr>{items}</table>{more}</section>")


def in_office(w, L) -> str:
    """The main page's short list of current office holders: the latest appointments."""
    return current(w, L, 6, latest=True)


def decades(w, L) -> str:
    n: dict[int, Counter] = {}
    peak: dict[int, tuple[int, int]] = {}
    for y, events in w.years.items():
        d = y // 10 * 10
        k = n.setdefault(d, Counter())
        for kind, _, _ in events:
            k["births" if kind == "births" else "deaths" if kind == "deaths" else "offices"] += 1
        if len(events) > peak.get(d, (0, 0))[0]:
            peak[d] = (len(events), y)
    if len(n) < 3:
        return ""
    lo, hi = min(n), max(n)
    ds = list(range(lo, hi + 1, 10))
    top = max(sum(n.get(d, {}).values()) for d in ds) or 1
    W, H, base, gap = 800, 150, 120, 4
    bw = (W - 20) / len(ds)
    parts = []
    for i, d in enumerate(ds):
        k, x, y0 = n.get(d, Counter()), 10 + i * bw, base
        tip = f"{d}s: {k['births']} births, {k['deaths']} deaths, {k['offices']} office changes"
        bars = []
        for key, cls in (("births", "dc-b"), ("deaths", "dc-d"), ("offices", "dc-o")):
            h = k[key] / top * (base - 10)
            if h:
                y0 -= h
                bars.append(f"<rect class={cls} x='{x:.1f}' y='{y0:.1f}' width='{bw - gap:.1f}' height='{h:.1f}'/>")
        link = L.year(peak[d][1]) if d in peak else ""
        label = f"<text class=lb-axis x='{x + (bw - gap) / 2:.1f}' y='{H - 8}' text-anchor=middle>{d}s</text>" \
            if len(ds) <= 16 or i % 2 == 0 else ""
        parts.append((f"<a href='{e(link)}'>" if link else "<g>") + f"<title>{e(tip)}</title>{''.join(bars)}{label}"
                     + ("</a>" if link else "</g>"))
    legend = ("<span class=key><i class=dc-b></i>births</span><span class=key><i class=dc-d></i>deaths</span>"
              "<span class=key><i class=dc-o></i>offices taken and left</span>")
    return (f"<section class='panel wide decades'><h2>Timeline</h2>"
            f"<svg viewBox='0 0 {W} {H}' width='100%' role=img aria-label='events by decade' class=decadesvg>"
            f"{''.join(parts)}</svg><p class=meta>{legend} · each bar opens its busiest year; "
            f"<a href='{L.years()}'>all years</a></p></section>")


def _short(text: str, n: int = 90) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def changes(w, limit: int = 8) -> list[dict]:
    """The archive's latest changes, each as `history.describe` puts it, newest first; those that changed
    no record, id or decision (a rebuild) are left out. Kept on the wiki: a snapshot never changes."""
    try:
        snaps = history.log(w.root, None, limit * 4) if history.enabled(w.root) else []
    except (SystemExit, OSError, ValueError, KeyError):      # history is optional, and never what stops the page
        return []
    cache = w.__dict__.setdefault("_described", {})
    out = []
    for s in snaps:
        if s["id"] not in cache:
            try:
                cache[s["id"]] = history.describe(w.root, s["id"])
            except (SystemExit, OSError, ValueError, KeyError):
                cache[s["id"]] = None
        d = cache[s["id"]]
        if d and (d["collections"] or d["published"] or d["decisions"] or d["settings"] or d["message"]):
            out.append(d)
        if len(out) >= limit:
            break
    return out


def new_entries(w, d: dict, limit: int = 6) -> list[str]:
    """The listed pages a change added records to, in the order the records were added."""
    seen = []
    for c in d["collections"]:
        for rid in c["added"]:
            b = w.body_of_record(rid)
            if b and b in w.listed and b not in seen:
                seen.append(b)
            if len(seen) >= limit:
                return seen
    return seen


def _who(d: dict) -> str:
    a = str(d.get("author") or "")
    return "through hydra-mcp" if a.startswith("agent:hydra-mcp") else a


def recent(w, L) -> str:
    rows = changes(w, 6)
    if not rows:
        return ""
    items = []
    for d in rows:
        title = d["message"] or d["headline"]
        sub = d["headline"] if d["message"] else ""
        ents = new_entries(w, d, 4)
        review = f" · <a href='{L.change(d['sid'])}'>Review</a>" if L.change(d["sid"]) else ""
        items.append(f"<li><div class=chg-title>{e(title)}</div>"
                     + (f"<div class=meta>{e(sub)}</div>" if sub else "")
                     + (f"<div class=chg-new>{' · '.join(w.a(L, b) for b in ents)}</div>" if ents else "")
                     + f"<div class=meta>{e(d['time'][:10])}" + (f" · {e(_who(d))}" if _who(d) else "") + f"{review}</div></li>")
    more = f"<p class=meta><a href='{L.changes()}'>All history →</a></p>" if L.changes() else ""
    return f"<section class=panel><h2>Recent changes</h2><ul class=recent>{''.join(items)}</ul>{more}</section>"


def added(w, L) -> str:
    """The entries the latest changes brought in."""
    bodies = []
    for d in changes(w, 6):
        for b in new_entries(w, d, 12):
            if b not in bodies:
                bodies.append(b)
        if len(bodies) >= 8:
            break
    if not bodies:
        return ""
    cards = "".join(f"<li><span class=ic>{icons.for_schema(w.root, w.pages[b]['schema'], 14)}</span>{w.a(L, b)}"
                    f"<span class=meta>{e(w.type_label(w.pages[b]['schema']))}</span></li>" for b in bodies[:8])
    return f"<section class=panel><h2>New entries</h2><ul class=newlist>{cards}</ul></section>"


def _short_money(w, b) -> str:
    """A price as a list reads it: "6 billion USD", "702 million USD"; the exact figure is on the deal's page."""
    amt, cur = w.first(b, "amount"), w.first(b, "currency") or ""
    try:
        v = float(amt)
    except (TypeError, ValueError):
        return ""
    for size, word in ((1e9, "billion"), (1e6, "million")):
        if v >= size:
            return f"{v / size:,.1f}".rstrip("0").rstrip(".") + f" {word} {cur}".rstrip()
    return f"{v:,.0f} {cur}".strip()


def deals(w, L) -> str:
    """The latest dated deals, with their price as the source gives it."""
    rows = [(str(w.first(b, "date") or ""), b) for b in w.listed if w.pages[b]["schema"] == w.reg_for(w.pages[b]).roles.EVENT and w.first(b, "date")]
    rows.sort(key=lambda x: (x[0], w.title(x[1])), reverse=True)
    if not rows:
        return ""
    items = "".join(f"<tr><td class=meta>{e(d[:4])}</td><td>{w.a(L, b)}</td><td class=num>{e(_short_money(w, b))}</td></tr>"
                    for d, b in rows[:7])
    return (f"<section class=panel><h2>Deals <span class=meta>({len(rows)})</span></h2>"
            f"<table class=list>{items}</table></section>")


def groups(w, L) -> str:
    """The groups groups.yaml defines (houses, parties...), each with how many entries are in it."""
    found = sorted(((k, len(v)) for (kind, k), v in w.cats.items() if kind == "group"), key=lambda x: (-x[1], x[0]))
    if not found:
        return ""
    label = next((g.get("label") for g in w.groups.values() if g.get("label")), "Group")
    chips = "".join(f"<a href='{L.cat('group', k)}'>{e(k)} <span class=meta>{n}</span></a>" for k, n in found[:24])
    return f"<section class=panel id=groups><h2>{e(label)}s</h2><p class=tags>{chips}</p></section>"


def attention(w, L) -> str:
    if not hasattr(w, "_findings"):
        try:
            w._findings = readiness.check(w.root)
        except (OSError, ValueError, KeyError):
            w._findings = []
    rank = {"warning": 0, "info": 1}
    found = sorted(w._findings, key=lambda f: (rank.get(f["level"], 2), -f["count"]))[:6]
    if not found:
        return ""
    items = "".join(f"<li class='lv-{e(f['level'])}'><b>{f['count']:,}</b> {e(f['what'])}"
                    f"<div class=meta>e.g. {e('; '.join(_short(x) for x in f['examples'][:2]))}</div></li>" for f in found)
    return (f"<section class='panel quiet'><h2>Data quality</h2><ul class=attn>{items}</ul>"
            f"<p class=meta>Full list: <code>hydra-ctl wiki &lt;dir&gt; check</code></p></section>")


SECTIONS = {f.__name__: f for f in (domains, featured, current, decades, recent, attention, added, deals, groups,
                                     explore, people, years_ago, in_office)}


def _weight(html_: str) -> int:
    """About how tall a section is: its text, plus a line per row or item."""
    return len(re.sub(r"<[^>]+>", "", html_)) + 60 * len(re.findall(r"<(?:tr|li)\b", html_))


def render(w, L, names=None) -> str:
    """The sections in order (wiki.yaml `landing:` for the main page). A wide one spans the page; the others
    between two wide ones fill two columns, each going to the shorter, so a tall card leaves no hole."""
    names = names or w.conf.get("landing") or ORDER
    out, group = [], []

    def flush():
        if len(group) == 1:
            out.append(group[0])
        elif group:
            cols, height = ([], []), [0, 0]
            for s in group:
                i = 0 if height[0] <= height[1] else 1
                cols[i].append(s)
                height[i] += _weight(s)
            out.append("<div class=cols>" + "".join(f"<div class=col>{''.join(c)}</div>" for c in cols) + "</div>")
        group.clear()
    for n in names:
        s = SECTIONS[n](w, L) if n in SECTIONS else ""
        if not s:
            continue
        if "class='wide" in s or "wide " in s.split(">", 1)[0]:
            flush()
            out.append(s)
        else:
            group.append(s)
    flush()
    return f"<div class=landing>{''.join(out)}</div>"
