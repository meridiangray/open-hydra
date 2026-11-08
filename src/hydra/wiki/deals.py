"""deals.py — ownership, holdings and deals: who owns what, in what share, and who acted for whom.

Same rules as views.py: only what the records say, every row footnoted to its record. A
share, a status and a capacity are shown as the record gives them; what a status or capacity
word means (over, a caveat, not the beneficiary) is read from .hydra/rules/vocabularies.yaml,
never named here. The one thing read from the data rather than stated is `identical_interest`
(.hydra/rules/capacity.yaml): a person who holds an office in the client they acted for is
shown "by their office", and the page says that it was read from the office.

    owners      who owns this, their share, since when, and the deal it came in         Ownership (asset end)
    holdings    what this owns, share, and the deal                                     Ownership (owner end)
    parties     a deal's page: who acted for whom in what capacity, and who owns what   Representation, Ownership
    acted_for   the deals this acted in, for whom, and the capacity (and who acted for it)  Representation
    deals       the deals this owner, asset or agent appears in                         `transaction`
"""
from __future__ import annotations

import html

from hydra import dates, vocab
from hydra.wiki import icons, views

e = html.escape


def pct(r):
    try:
        return float(str(r.get("percentage") or "").rstrip("% "))
    except ValueError:
        return None


def when(r) -> str:
    """A holding's period: "1992–2021", "since 1994" or "until 2007" when one end is not recorded, else its date."""
    a, b = r.get("startDate"), r.get("endDate")
    if a and b:
        return views.span(a, b, r.get("approx"))
    ap = (r.get("approx") or {})
    a, b = (dates.show(a, ap.get("startDate") or ap.get("date")) if a else a,
            dates.show(b, ap.get("endDate")) if b else b)
    return f"since {a}" if a else f"until {b}" if b else str(dates.show(r.get("date"), ap.get("date")) if r.get("date") else "")


def _status(w, r) -> dict:
    return vocab.meaning(w.vocab, r.get("edge") or "", "status", r.get("status"))


def _former(w, r) -> bool:
    """Over: the record has an end date, or its status is one the vocabulary marks `ended`."""
    return bool(r.get("endDate")) or bool(_status(w, r).get("ended"))


def _order(w, r) -> tuple:
    """Where a record falls in time: its first year (else its end year, else its date); a former one before a current one."""
    return (str(r.get("startDate") or r.get("endDate") or r.get("date") or "9999")[:4], 0 if _former(w, r) else 1)


def status_chip(w, r) -> str:
    st = str(r.get("status") or "")
    if not st:
        return ""
    cfg = _status(w, r)
    label, why, tone = cfg.get("label", st.capitalize()), cfg.get("why", ""), cfg.get("tone", "")
    return f"<span class='badge status {tone}' title='{e(why)}'>{e(label)}</span>"


def share(r) -> str:
    v = pct(r)
    if v is None:
        return "<span class=meta>not recorded</span>"
    return f"<span class=share><i style='width:{min(v, 100):.1f}%'></i></span> {e(str(r['percentage']).rstrip('%'))}%"


def money(w, ev) -> str:
    amt, cur = w.first(ev, "amount"), w.first(ev, "currency")
    try:
        return f"{float(amt):,.0f} {cur or ''}".strip()
    except (TypeError, ValueError):
        return ""


def deals_of(r, prop: str = "transaction") -> list[str]:
    """Every deal a relationship names (a stake bought in one deal and sold in another names both)."""
    return (r.get("links") or {}).get(prop) or ([r[prop]] if r.get(prop) else [])


def deal_link(w, c, r) -> str:
    ts = [t for t in deals_of(r) if t in w.pages]
    if not ts:                                 # a deal named but not found: shown red or marked, never dropped
        miss = next((x for x in r.get("context") or () if x["prop"] == "transaction"), None)
        return c.a(miss) if miss else "<span class=meta>—</span>"
    return "<br>".join(c.a(t) + (f" <span class=meta>{e(str(d))}</span>" if (d := w.first(t, "date")) else "")
                       for t in sorted(ts, key=lambda t: str(w.first(t, "date") or "")))


def capacity_label(w, r) -> str:
    key = r.get("capacity")
    cap = vocab.meaning(w.vocab, r.get("edge") or w.reg_for(r).roles.REPRESENTATION, "capacity", key)
    return cap.get("label") or str(key or "").capitalize() or "—"


def basis(w, c, agent: str, client: str) -> str:
    """How an agent's office ties them to the client, read from their own links, or ''."""
    cfg = w.capacity.get("identical_interest") or {}
    via, page = set(cfg.get("via") or ()), w.pages.get(agent)
    if not page:
        return ""
    for r in page["relations"]:
        if r.get("edge") not in via or r.get("side") != "source" or not r.get("other"):
            continue
        org = r["other"]
        if r["edge"] == c.reg.roles.TENURE:                # `other` is the post: its body is the client
            org = w.first(r["other"], "organization")
        if org == client:
            return (f"{c.a(r['other'])} <span class=meta>({e(cfg.get('mark') or 'by their office')}; read from the office, "
                    f"not stated by the deal's source)</span>{c.sup(r['cites'])}")
    return ""


def _table(head: list[str], rows: list[str], cls: str = "wikitable") -> str:
    return (f"<table class='{cls}'><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr>"
            f"{''.join(f'<tr>{x}</tr>' for x in rows)}</table>")


def owners(p, c: views.Ctx) -> str:
    rs = c.rels(p, c.reg.roles.OWNERSHIP, "target")
    if not rs:
        return ""
    rs = sorted(rs, key=lambda r: (_former(c.wiki, r), -(pct(r) or 0), _order(c.wiki, r), c.wiki.title(r)))
    rows = [f"<td>{c.a(r)}{c.sup(r['cites'])}</td><td class=nw>{share(r)}</td><td class=nw>{status_chip(c.wiki, r)}</td>"
            f"<td class=nw>{e(when(r))}</td><td>{deal_link(c.wiki, c, r)}</td>" for r in rs]
    cur = [pct(r) for r in rs if not _former(c.wiki, r) and pct(r) is not None]
    note = (f"<p class=meta>Recorded shares total {sum(cur):.2f}%.</p>"
            if len(cur) > 1 else "")
    tip = "Negotiators and signatories aren't owners; they're on the deal's page." if any(r.get("transaction") for r in rs) else ""
    return f"<h2 id=owners>Owners{views.info(tip) if tip else ''}</h2>" + _table(["Owner", "Share", "Status", "Period", "Deal"], rows) + note


def provenance(p, c: views.Ctx) -> str:
    """An asset's owners in order, as boxes: who held it, when, and the deal. Ordered by the dates the records give;
    nothing between two owners is filled in."""
    rs = c.rels(p, c.reg.roles.OWNERSHIP, "target")
    if len(rs) < 2 or not any(r.get("startDate") or r.get("endDate") or r.get("date") for r in rs):
        return ""
    boxes = []
    for r in sorted(rs, key=lambda r: _order(c.wiki, r)):
        w = when(r) or "no date recorded"
        boxes.append(f"<div class='link{' now' if not _former(c.wiki, r) else ''}'><b>{c.a(r)}</b>{c.sup(r['cites'])}"
                     f"<div class=meta>{e(w)}</div>{status_chip(c.wiki, r)}</div>")
    return ("<h2 id=provenance>Chain of ownership</h2><div class=chain>" + "<span class=arrow>→</span>".join(boxes)
            + "</div>")


def holdings(p, c: views.Ctx) -> str:
    rs = c.rels(p, c.reg.roles.OWNERSHIP, "source")
    if not rs:
        return ""
    rs = sorted(rs, key=lambda r: (_former(c.wiki, r), -(pct(r) or 0), c.wiki.title(r)))

    def kind(r):
        pg = c.page(r.get("other")) or {}
        return (f"<span class=kindchip>{icons.for_schema(c.wiki.root, pg.get('schema', ''), 14)}"
                f"{e(c.wiki.type_label(pg.get('schema', '')))}</span>")
    details = [detail(c, c.page(r.get("other")) or {}) for r in rs]
    more = any(details)                                    # the column is there only when some asset has something to say
    rows = [f"<td>{c.a(r)}{c.sup(r['cites'])}</td><td>{kind(r)}</td>" + (f"<td class=detailcell>{d}</td>" if more else "")
            + f"<td class=nw>{share(r)}</td><td class=nw>{status_chip(c.wiki, r)}</td><td class=nw>{e(when(r))}</td><td>{deal_link(c.wiki, c, r)}</td>"
            for r, d in zip(rs, details)]
    head = ["Asset", "Kind"] + (["Detail"] if more else []) + ["Share", "Status", "Period", "Deal"]
    return "<h2 id=holdings>Holdings</h2>" + _table(head, rows)


DETAIL_SKIP = {"name", "amount", "owner"}       # the title, the price, and the owner (the page already says who)
DETAIL_SHOWN = 2
CODE_TYPES = {"identifier", "imo", "iban", "checksum"}      # values that are codes: set in a fixed-width face


def detail(c: views.Ctx, pg: dict) -> str:
    """What this kind of asset is known by: its schema's own featured properties that the record has (a vessel's flag and
    IMO number, an airplane's registration and operator, a property's address), up to two. Each is a small label with its
    value beside it; a country is its flag and name, a code (an IMO number, a registration) is set as a code."""
    s = pg.get("schema") or ""
    if s not in views.hschema.SCHEMA:
        return ""
    res = views.hschema.resolve(s)
    out = []
    for prop in res.get("featured") or []:
        if prop in DETAIL_SKIP or len(out) >= DETAIL_SHOWN:
            continue
        vals = [v for v in c.values(pg, prop) if not (v.get("h") or v.get("red") or v.get("unresolved")) and v.get("value")]
        if not vals:
            continue
        defn = res["props"].get(prop) or {}
        kind = views.STD.kind_of(s, prop, defn.get("type"))
        code = defn.get("type") in CODE_TYPES
        shown = ", ".join(views.country_html(v["value"]) if kind == "country"
                          else e(views.coded(kind, v["value"]) if kind else str(v["value"])) for v in vals[:2])
        if prop == "country":                              # a flag and a name say it: no label
            out.append(f"<dd class=solo>{shown}</dd>")
        else:
            out.append(f"<dt>{e(defn.get('label') or prop)}</dt><dd{' class=code' if code else ''}>{shown}</dd>")
    return f"<dl class=detail>{''.join(out)}</dl>" if out else ""


def _event_rows(w, tx: str) -> list:
    return w.tx.get(tx, [])


def parties(p, c: views.Ctx) -> str:
    if p["schema"] != c.reg.roles.EVENT:
        return ""
    w, out = c.wiki, []
    reps = [(b, r) for b, r in _event_rows(w, p["body"]) if r["edge"] == c.reg.roles.REPRESENTATION]
    if reps:
        rows = []
        for b, r in sorted(reps, key=lambda x: (w.title(x[0]), w.title(x[1]))):
            how = basis(w, c, b, r.get("other")) or "<span class=meta>stated by the source only</span>"
            rows.append(f"<td>{c.a(b)}</td><td>{e(capacity_label(w, r))}"
                        f"<div class=meta>{e(r.get('role') or '')}</div></td><td>{c.a(r)}{c.sup(r['cites'])}</td>"
                        f"<td>{how}</td><td>{status_chip(w, r)}</td>")
        out.append("<h2 id=parties>Who acted for whom</h2>"
                   + _table(["Acted", "Capacity", "For", "Tie to the client", "Status"], rows)
                   + "<p class=meta>Acting for someone doesn't make them an owner. Owners are listed below.</p>")
    owns = [(b, r) for b, r in _event_rows(w, p["body"]) if r["edge"] == c.reg.roles.OWNERSHIP]
    if owns:
        rows = [f"<td>{c.a(b)}</td><td>{c.a(r)}{c.sup(r['cites'])}</td><td class=nw>{share(r)}</td><td>{status_chip(w, r)}</td>"
                f"<td class=nw>{e(when(r))}</td>" for b, r in sorted(owns, key=lambda x: (_former(w, x[1]), w.title(x[0])))]
        out.append("<h2 id=ownership>Ownership in this deal</h2>" + _table(["Owner", "Asset", "Share", "Status", "Period"], rows))
    involved = [(b["label"], v) for b in p["infobox"] if b["prop"] in ("involved", "organizer")
                for v in b["values"]]
    more = [(b, r) for b, r in _event_rows(w, p["body"]) if r["edge"] not in (c.reg.roles.REPRESENTATION, c.reg.roles.OWNERSHIP)]
    if involved or more:                     # an event that is no deal: who and what took part in it
        rows = [f"<td>{e(label)}</td><td>{c.a(v)}{c.sup(v['cites'])}</td>" for label, v in involved]
        rows += [f"<td>{e(r['edge'])}</td><td>{c.a(b)} {e(r.get('verb') or '')} {c.a(r)}{c.sup(r['cites'])}</td>"
                 for b, r in sorted(more, key=lambda x: (x[1]["edge"], w.title(x[0]), w.title(x[1])))]
        out.append("<h2 id=participants>Participants</h2>" + _table(["Part", "Entry"], rows))
    return "".join(out)


def acted_for(p, c: views.Ctx) -> str:
    w, out = c.wiki, []
    mine = c.rels(p, c.reg.roles.REPRESENTATION, "source")
    if mine:
        rows = [f"<td>{deal_link(w, c, r)}</td><td>{c.a(r)}{c.sup(r['cites'])}</td>"
                f"<td>{e(capacity_label(w, r))}<div class=meta>{e(r.get('role') or '')}</div></td>"
                f"<td>{basis(w, c, p['body'], r.get('other')) or '<span class=meta>stated by the source only</span>'}</td>"
                f"<td>{status_chip(w, r)}</td>" for r in sorted(mine, key=lambda r: (r.get("transaction") or "", w.title(r)))]
        out.append("<h2 id=acted-for>Acted for</h2>" + _table(["Deal", "For", "Capacity", "Tie to the client", "Status"], rows))
    theirs = c.rels(p, c.reg.roles.REPRESENTATION, "target")
    if theirs:
        rows = [f"<td>{c.a(r)}{c.sup(r['cites'])}</td><td>{deal_link(w, c, r)}</td>"
                f"<td>{e(capacity_label(w, r))}</td><td>{status_chip(w, r)}</td>" for r in theirs]
        out.append("<h2 id=acted-for-by>Acted for by</h2>" + _table(["Agent", "Deal", "Capacity", "Status"], rows))
    return "".join(out)


def deals(p, c: views.Ctx) -> str:
    """Every deal this entry's own records (ownership as owner or asset, representation) name."""
    w, seen = c.wiki, {}
    for r in p["relations"]:
        for t in deals_of(r):
            if t in w.pages and r.get("edge") in (c.reg.roles.OWNERSHIP, c.reg.roles.REPRESENTATION, "Payment"):
                seen.setdefault(t, r)
    if not seen:
        return ""
    rows = [f"<td>{c.a(t)}</td><td>{e(str(w.first(t, 'date') or ''))}</td><td>{e(money(w, t))}</td>"
            f"<td class=meta>{e(r.get('edge'))}: {e(r.get('verb') or '')}</td>"
            for t, r in sorted(seen.items(), key=lambda kv: str(w.first(kv[0], "date") or ""))]
    return "<h2 id=deals>Deals</h2>" + _table(["Deal", "Date", "Price", "This entry's part"], rows)


def infobox_rows(p, c: views.Ctx) -> list[tuple[str, str]]:
    """Rows the infobox adds for ownership: an asset's or company's owners, a deal's date and price."""
    w, out = c.wiki, []
    s = p["schema"]
    if s == c.reg.roles.EVENT:
        price = money(w, p["body"])
        if price:
            out.append(("Price", e(price) + " <span class=meta>as the source gives it</span>"))
        parts = {b for b, _ in _event_rows(w, p["body"])} | {r.get("other") for _, r in _event_rows(w, p["body"]) if r.get("other")}
        if parts:
            out.append(("Parties", "<br>".join(c.a(b) for b in sorted(filter(None, parts), key=w.title)[:8])))
        return out
    cur = [r for r in c.rels(p, c.reg.roles.OWNERSHIP, "target") if not _former(c.wiki, r)]
    if cur:
        top = sorted(cur, key=lambda r: -(pct(r) or 0))[:4]
        out.append(("Owner" if len(cur) == 1 else "Owners", "<br>".join(
            f"{c.a(r)}{' <span class=meta>' + e(str(r['percentage']).rstrip('%')) + '%</span>' if pct(r) is not None else ''}"
            f"{' ' + status_chip(w, r) if _status(w, r).get('caveat') else ''}" for r in top)
            + (f"<br><a href='#owners'>all {len(cur)}</a>" if len(cur) > 4 else "")))
    held = c.rels(p, c.reg.roles.OWNERSHIP, "source")
    if held:
        out.append(("Holdings", f"<a href='#holdings'>{len(held)} recorded</a>"))
    return out


views.SECTIONS.update(provenance=provenance, owners=owners, holdings=holdings, parties=parties, acted_for=acted_for, deals=deals)
views.INFOBOX_EXTRA.append(infobox_rows)
