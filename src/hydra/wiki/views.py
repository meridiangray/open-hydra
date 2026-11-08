"""views.py — the display methods: how one page's data becomes Wikipedia sections.

Each method takes the page and a Ctx (every page, the link maker, the page's
footnotes) and returns HTML, or "" when the page has nothing for it. They say
only what the records say: a sentence is assembled from values, and every
value keeps its footnote back to the record that supplied it.

    method        what it shows                                   from
    hatnote       "Not to be confused with ..." (same name)       also
    lead          the opening sentence                            dates, offices, parents
    infobox       a schema's own rows, then any other value       properties, images, relations
    offices       offices held, term and time in office           Occupancy
    holders       a post's numbered officeholders, incumbent      Occupancy, the post's side
    positions     the posts inside a body, latest holder each      Position.organization
    family        parents, siblings, issue by the other parent    Family father / mother
    succession    preceded by | office | succeeded by boxes       Occupancy, ordered per post
    timeline      dated events in order, years linked              dates, terms
    recorded      the "as recorded" lines, verbatim               notes
    references    footnotes with their quote, document, link      citations
    links         external links, deduplicated and named           urls in records and notes
    categories    births, deaths, office, group, member, type     all of the above, groups.yaml

    lifebar       birth to death with the offices as bars         dates, terms        (visuals.py)
    ancestors     parents, grandparents, great-grandparents       Family father / mother
    navboxes      the foot boxes: a post's holders, a group        Occupancy, groups.yaml, collections

Which methods a page gets: METHODS by schema (names, in order), over which wiki.yaml `sections:` may say otherwise.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from collections import defaultdict

from hydra import dates, kinship, standards
from hydra import schema as hschema
from hydra.wiki import assets, icons, roles
from hydra.wiki.reg import Roles
from hydra.wiki import badges as dbadges

e = html.escape

STD = standards.load()        # the archive's code lists (ISO names, demonyms): Wiki sets its own on load
NOTE_LINE = re.compile(r"^([A-Z][A-Za-z ]{1,30}):\s*(.+)$")
URL = re.compile(r"\[?(https?://[^\s\]\)>,]+)\]?")
DERIVED = re.compile(r"derived from (the |office )?title", re.I)      # the importer's remark on a record it made
AS_RECORDED = re.compile(r"^(?:as recorded|recorded as|roles? as recorded)\s*:\s*", re.I)  # a note's label, already shown under "As recorded"


TYPES = {"Person": ("Person", "People"), "PublicBody": ("Public body", "Public bodies"),
         "Organization": ("Organization", "Organizations"), "Company": ("Company", "Companies"),
         "LegalEntity": ("Legal entity", "Legal entities"), "Position": ("Office", "Offices"),
         "Document": ("Document", "Documents"), "Address": ("Address", "Addresses"),
         "Event": ("Deal or event", "Deals and events"), "Vehicle": ("Vehicle", "Vehicles"), "Asset": ("Asset", "Assets"),
         "RealEstate": ("Real estate", "Real estate"), "Vessel": ("Vessel", "Vessels")}


def type_label(schema: str, plural: bool = False) -> str:
    """An FtM type as a reader says it: `PublicBody` -> "Public body" / "Public bodies"."""
    if schema in TYPES:
        return TYPES[schema][1 if plural else 0]
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", schema or "").capitalize()
    return (words + "s") if plural and words else words


def country(code: str) -> str:
    """A country code as a reader says it: ISO 3166 (current or former), or standards.yaml's name."""
    return STD.label("country", code)


def country_html(code: str) -> str:
    """A country as a reader sees it: its flag, when there is one to draw, then its name."""
    from hydra.wiki import flags
    return flags.img(code) + e(country(code))


def coded(kind: str, code: str) -> str:
    """A code of any standard (currency, language, script...) as a reader says it."""
    return STD.label(kind, code)


year = dates.year

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def long_date(iso: str) -> str:
    """'2026-11-05' -> '5 November 2026'; anything else as it is."""
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", iso or "")
    return f"{int(m[3])} {MONTHS[int(m[2]) - 1]} {m[1]}" if m and 1 <= int(m[2]) <= 12 else (iso or "")


def span(a, b, approx=None) -> str:
    """"2008–2014", with a record's `_meta.approx` qualifiers when given: ("c. 1748", None)."""
    ap = approx or {}
    a = dates.show(a, ap.get("startDate") or ap.get("date")) if a else a
    b = dates.show(b, ap.get("endDate")) if b else b
    return "–".join(str(x) for x in (a, b) if x) if (a or b) else ""


# Which kind of image a place wants, best first. A person's page leads with the portrait, a body's with its logo;
# a small picture beside a name (a table row, a card) takes a thumb before a full portrait.
PERSON_FIRST = ("portrait", "thumb", "logo")
BODY_FIRST = ("logo", "portrait", "thumb")
SMALL = ("thumb", "portrait", "logo")


def media(p) -> list[dict]:
    """[{kind, path}] of a page's images; pages built before `media` existed give their `images` with no kind."""
    return p.get("media") or [{"kind": "", "path": i} for i in p.get("images") or []]


def images(p, small: bool = False) -> list[dict]:
    """The page's images, the kind this place wants first (the order of one kind is the order the rules gave)."""
    want = SMALL if small else PERSON_FIRST if p.get("schema") == roles.PERSON else BODY_FIRST
    rank = lambda m: want.index(m["kind"]) if m["kind"] in want else len(want)
    return sorted(media(p), key=rank)


def image(p, small: bool = False) -> str | None:
    """The one image to show for a page, or None."""
    got = images(p, small)
    return got[0]["path"] if got else None


class Ctx:
    def __init__(self, wiki, L, page):
        self.wiki, self.L, self.p = wiki, L, page
        self.reg = wiki.reg_for(page)                  # the compiled lookups for this page's collection

    # -- reading other pages
    def page(self, b):
        return self.wiki.pages.get(b)

    def a(self, b) -> str:
        return self.wiki.a(self.L, b)

    def values(self, b_or_page, prop) -> list[dict]:
        p = b_or_page if isinstance(b_or_page, dict) else self.page(b_or_page)
        for box in (p or {}).get("infobox") or []:
            if box["prop"] == prop:
                return box["values"]
        return []

    def first(self, b, prop):
        v = self.values(b, prop)
        return (v[0].get("value") or v[0].get("h")) if v else None

    def life(self, b) -> str:
        if not b:
            return ""
        born, died = year(self.first(b, "birthDate")), year(self.first(b, "deathDate"))
        if born and died:
            return f"{born}–{died}"
        return f"b. {born}" if born else (f"d. {died}" if died else "")

    def rels(self, p, edge, side=None, verbs=None) -> list[dict]:
        return [r for r in p["relations"] if r.get("edge") == edge and (side is None or r.get("side") == side)
                and (verbs is None or r["verb"] in verbs)]

    def sup(self, ns) -> str:
        return self.wiki.sup(ns)

    def year_link(self, y) -> str:
        return f"<a href='{self.L.year(y)}'>{y}</a>" if y in self.wiki.years else str(y)

    def kin(self, p, kind) -> str:
        """How a page words a relative by their recorded gender (kinship.yaml `names`): kind
        "child" (or "son") -> son / daughter / child, "sibling" -> brother / sister / sibling."""
        g = self.first(p["body"] if isinstance(p, dict) else p, "gender")
        return self.wiki.kin.name({"son": "child"}.get(kind, kind), g)

    # -- derived
    def holders(self, post) -> list[dict]:
        """A post's terms, earliest first; terms without any year last."""
        p = self.page(post)
        if not p:
            return []
        terms = self.rels(p, self.reg.roles.TENURE, "target")
        key = lambda r: (year(r.get("startDate") or r.get("date") or r.get("endDate")) or 99999, self.wiki.title(r))
        return sorted(terms, key=key)

    def parents(self, p) -> dict:
        """{"father": r, "mother": r} ("parent" when no gender is known), read both ways a Family
        record can be written: a parent word on the child's record ("father"), or a child word on
        the parent's ("son"). The words are kinship.yaml's."""
        k, out = self.wiki.kin, {}
        for r in p["relations"]:
            if r.get("edge") != self.reg.roles.KIN:
                continue
            v = r["verb"]
            if r.get("side") == "source" and k.is_(v, "parent"):          # the relative is p's parent
                g = k.gender(v) or self.first(r.get("other"), "gender")
            elif r.get("side") == "target" and str(v).endswith(" of") and k.is_(v, "child"):   # p is the record's child
                g = self.first(r.get("other"), "gender")
            else:
                continue
            out.setdefault(k.name("parent", g), r)
        return out

    def children(self, p) -> list[dict]:
        k = self.wiki.kin
        kids = [r for r in p["relations"] if r.get("edge") == self.reg.roles.KIN and (
                (r.get("side") == "target" and str(r["verb"]).endswith(" of") and k.is_(r["verb"], "parent"))
                or (r.get("side") == "source" and k.is_(r["verb"], "child")))]
        return sorted({r.get("other") or ("name", r.get("name")): r for r in kids}.values(),
                      key=lambda r: (year(self.first(r.get("other"), "birthDate")) or 99999, self.wiki.title(r)))

    def other_parent(self, p, kid) -> str | None:
        kp = self.page(kid.get("other")) or {"relations": []}
        return next((x["other"] for x in self.parents(kp).values() if x.get("other") and x["other"] != p["body"]), None)

    def stated_spouses(self, p) -> list[dict]:
        """The explicit spouse edges the records state (a Family record saying spouse), as relations."""
        k = self.wiki.kin
        return [r for r in p["relations"] if r.get("edge") == self.reg.roles.KIN and r.get("other")
                and r["other"] != p["body"] and k.is_(r["verb"], "spouse")]

    def spouses(self, p) -> list[tuple[str | None, list[dict]]]:
        """[(other parent or stated spouse, their children)] in order of the first child's birth.
        A spouse comes from an explicit Family edge, or is read from shared children (marked
        as such by the caller when no explicit record exists). None: other parent unknown."""
        groups = {}
        for r in self.children(p):
            groups.setdefault(self.other_parent(p, r), []).append(r)
        out = sorted(groups.items(), key=lambda kv: kv[0] is None)
        known = {g[0] for g in out}
        return out + [(r["other"], []) for r in self.stated_spouses(p) if r["other"] not in known]

    def siblings(self, p) -> list[tuple[str, list[dict]]]:
        """[(label, rels)]: the children of either recorded parent — full when they share every
        recorded parent (both recorded: "Full siblings"), half by the one they share — plus the
        explicit sibling edges ("Siblings")."""
        par = self.parents(p)
        known = {kk: r["other"] for kk, r in par.items() if r.get("other")}
        kids: dict[str, dict] = {}
        for b in known.values():
            for r in self.children(self.page(b) or {"relations": []}):
                if r.get("other") and r["other"] != p["body"]:
                    kids.setdefault(r["other"], r)
        stated = [r for r in p["relations"] if r.get("edge") == self.reg.roles.KIN and r.get("other")
                  and r["other"] != p["body"] and self.wiki.kin.is_(r["verb"], "sibling")]
        for r in stated:
            kids.setdefault(r["other"], r)
        full, paternal, maternal, plain = [], [], [], []
        for b, r in sorted(kids.items(), key=lambda kv: (year(self.first(kv[0], "birthDate")) or 99999,
                                                       self.wiki.title(kv[1]))):
            theirs = {x["other"] for x in self.parents(self.page(b) or {"relations": []}).values() if x.get("other")}
            shared = set(known.values()) & theirs
            if shared and shared == set(known.values()) and len(known) == 2:
                full.append(r)
            elif shared:
                (paternal if known.get("father") in shared else maternal).append(r) \
                    if len(known) == 2 else plain.append(r)
            else:
                plain.append(r)
        return [x for x in (("Full siblings", full), ("Siblings", plain),
                            ("Paternal half-siblings", paternal), ("Maternal half-siblings", maternal)) if x[1]]

    def is_latest(self, who: str, term) -> bool:
        """Is `term` (read from person `who`'s page) the last term of its post? The post's own
        page holds the same term as another dict, so it is matched by holder and dates."""
        last = (self.holders(term["other"]) or [None])[-1]
        return bool(last) and (last["other"], last.get("startDate"), last.get("endDate")) \
            == (who, term.get("startDate"), term.get("endDate"))

    def incumbent(self, term) -> bool:
        """The last term of a post, begun, with no end and no death recorded."""
        return bool(year(term.get("startDate") or term.get("date")) and not term.get("endDate")
                    and term.get("other") and not self.first(term["other"], "deathDate"))


def cycle(c: "Ctx", p) -> str:
    """The infobox's picture: the best image, and when the page has more, buttons to step through them (all are
    shown one under another when scripts are off). The kind is the caption: portrait, logo, thumb."""
    got = images(p)
    if not got:
        return ""
    several = len(got) > 1
    cap = lambda m: f"<figcaption>{e(m['kind'])}</figcaption>" if several and m["kind"] else ""
    imgs = "".join(f"<figure><img src='{c.L.asset(m['path'])}' alt='' loading=lazy>{cap(m)}</figure>" for m in got)
    if len(got) < 2:
        return f"<tr><td colspan=2 class=img>{imgs}</td></tr>"
    return (f"<tr><td colspan=2 class=img><div class=cycle data-n={len(got)}>{imgs}"
            "<div class=cyclebar><button type=button class=prev aria-label='Previous image'>‹</button>"
            f"<span class=pos>1 / {len(got)}</span>"
            "<button type=button class=next aria-label='Next image'>›</button></div>"
            f"<script>{assets.script('cycle.js')}</script></div></td></tr>")


# --------------------------------------------------------------------- methods

def info(text: str) -> str:
    """A small "i" beside a heading: the standing explanation of a section, as a tooltip rather than a paragraph."""
    return f" <span class=info tabindex=0 role=note title='{e(text)}' aria-label='{e(text)}'>i</span>"


def hatnote(p, c: Ctx) -> str:
    out = []
    if p["also"]:
        others = ", ".join(f"{c.a(b)}{' (' + c.life(b) + ')' if c.life(b) else ''}" for b in p["also"])
        out.append(f"<div class=hatnote>Not to be confused with {others}. "
                   f"<a href='{c.L.talk(p['body'])}'>Same name, not merged: review</a></div>")
    key = c.wiki.name_key(p["title"])
    if len(c.wiki.names.get(key, ())) > 1 and set(c.wiki.names[key]) - {p["body"], *p["also"]}:
        out.append(f"<div class=hatnote>For other entries named {e(p['title'])}, see "
                   f"<a href='{c.L.name(key)}'>{e(p['title'])} (disambiguation)</a>.</div>")
    return "".join(out)


def _offices(p, c: Ctx) -> list[dict]:
    terms = c.rels(p, c.reg.roles.TENURE, "source")
    return sorted(terms, key=lambda r: (year(r.get("startDate") or r.get("date")) or 99999, c.wiki.title(r)))


LEAD: dict = {}                                     # wiki.yaml `lead:`: {schema: template, or False for none}
LEAD_SLOTS = {"name", "life", "was", "demonym", "offices", "office_count", "more", "parents", "kin",       # a person
              "org", "holders", "since", "latest", "latest_from",                                        # a position
              "kind", "country", "posts"}                                                                  # a body


def configure_lead(given: dict | None) -> None:
    """wiki.yaml `lead: {Person: "{name} {life} held {offices}[; {kin} of {parents}].", Position: false}`: the opening
    sentence of a page. `[...]` vanishes when a slot inside it is empty; False writes no sentence. Slots: LEAD_SLOTS."""
    if given is not None and not isinstance(given, dict):
        raise ValueError("wiki.yaml lead: must be a mapping of schema name to a template (or false)")
    for k, t in (given or {}).items():
        if t is False:
            continue
        if not isinstance(t, str):
            raise ValueError(f"wiki.yaml lead: {k}: a template string, or false")
        if bad := set(re.findall(r"\{(\w+)\}", t)) - LEAD_SLOTS:
            raise ValueError(f"wiki.yaml lead: {k}: unknown slot(s) {sorted(bad)}; known: {sorted(LEAD_SLOTS)}")
    LEAD.clear()
    LEAD.update({str(k): t for k, t in (given or {}).items()})


def _lead_tpl(schema: str):
    for n in hschema.ancestors(schema) or (schema,):
        if n in LEAD:
            return LEAD[n]
    return None


def fill(tpl: str, slots: dict) -> str:
    t = e(tpl)
    t = re.sub(r"\[([^\[\]]*)\]", lambda m: m.group(1) if all(slots.get(n) for n in re.findall(r"\{(\w+)\}", m.group(1))) else "", t)
    t = re.sub(r"\{(\w+)\}", lambda m: str(slots.get(m.group(1), "")), t)
    return re.sub(r"\s+", " ", t).strip()


def lead(p, c: Ctx) -> str:
    s = p["schema"]
    name = f"<b>{e(p['title'])}</b>"
    paras = []
    if s == c.reg.roles.PERSON:
        born, died = c.values(p, "birthDate"), c.values(p, "deathDate")
        bits = []
        if born:
            place = c.values(p, "birthPlace")
            bits.append(f"{'born ' if not died else ''}{e(dates.show(born[0]['value'], born[0].get('approx')))}"
                        f"{(' in ' + e(place[0]['value'])) if place and not died else ''}{c.sup(born[0]['cites'])}")
        if died:
            bits.append(f"{e(dates.show(died[0]['value'], died[0].get('approx')))}{c.sup(died[0]['cites'])}")
        lifespan = f" ({' – '.join(bits)})" if bits else ""
        nat = c.first(p["body"], "nationality") or c.first(p["body"], "citizenship")
        demonym = STD.demonym(nat) if nat else ""
        offices = _offices(p, c)
        tense = "was" if died else "is"
        what = more = ps = ""
        if offices:
            depth = lambda r: ((c.page(r.get("other")) or {}).get("rank") or {}).get("depth")
            ranked = [r for r in offices if depth(r) is not None]
            shown = sorted(ranked, key=lambda r: depth(r))[:3] if ranked else offices[-3:]
            shown = sorted(shown, key=lambda r: year(r.get("startDate") or r.get("date")) or 99999)
            parts = [f"{c.a(r)}{' (' + span(r.get('startDate') or r.get('date'), r.get('endDate'), r.get('approx')) + ')' if span(r.get('startDate') or r.get('date'), r.get('endDate'), r.get('approx')) else ''}"
                     f"{c.sup(r['cites'])}" for r in shown]
            what = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
            more = f" (<a href='#offices'>{len(offices)} offices in all</a>)" if len(offices) > 3 else ""
            sentence = f"{name}{lifespan} {'served' if died else 'has served'} as {what}{more}"
        else:
            sentence = f"{name}{lifespan}" + (f" {tense} a {demonym} national" if demonym else "")
        par = c.parents(p)
        if par:
            ps = " and ".join(f"{c.a(r)}{c.sup(r['cites'])}" for k, r in sorted(par.items(), key=lambda kv: kv[0] != "father"))
            sentence += f"; {c.kin(p, 'son')} of {ps}"
        tpl = _lead_tpl(s)
        if tpl is None:
            paras.append(sentence + ".")
        elif tpl:
            paras.append(fill(tpl, {"name": name, "life": lifespan.strip(), "was": tense, "demonym": demonym, "offices": what,
                                    "office_count": str(len(offices) or ""), "more": more.lstrip(", "), "parents": ps,
                                    "kin": c.kin(p, "son") if par else ""}))
    elif s == c.reg.roles.POST:
        org = c.values(p, "organization")
        terms = c.holders(p["body"])
        sentence = f"{name} is a position" + (f" in {c.a(org[0]['h'])}{c.sup(org[0]['cites'])}" if org and org[0].get("h") else "")
        if terms:
            first = next((year(r.get("startDate") or r.get("date")) for r in terms if year(r.get("startDate") or r.get("date"))), None)
            last = terms[-1]
            n = len({r["other"] for r in terms})
            sentence += (f". {'One person has' if n == 1 else f'{n} people have'} held it"
                         f"{' since ' + str(first) if first else ''}; the most recent is {c.a(last['other'])}"
                         f"{' (from ' + str(year(last.get('startDate') or last.get('date'))) + ')' if year(last.get('startDate') or last.get('date')) else ''}"
                         f"{c.sup(last['cites'])}")
        tpl = _lead_tpl(s)
        if tpl is None:
            paras.append(sentence + ".")
        elif tpl:
            last = terms[-1] if terms else None
            first_y = next((year(r.get("startDate") or r.get("date")) for r in terms if year(r.get("startDate") or r.get("date"))), None)
            paras.append(fill(tpl, {"name": name, "org": f"{c.a(org[0]['h'])}{c.sup(org[0]['cites'])}" if org and org[0].get("h") else "",
                                    "holders": str(len({r["other"] for r in terms}) or ""), "since": str(first_y or ""),
                                    "latest": c.a(last["other"]) if last else "",
                                    "latest_from": str(year(last.get("startDate") or last.get("date")) or "") if last else ""}))
    elif hschema.is_a(s, "LegalEntity"):
        ctry = c.first(p["body"], "country")
        posts = _posts_in(p, c)
        sentence = f"{name} is {'a public body' if s == 'PublicBody' else 'an organization'}" + \
                   (f" in {e(country(ctry))}" if ctry else "")
        if posts:
            sentence += f", with {len(posts)} recorded position{'s' if len(posts) > 1 else ''}"
        tpl = _lead_tpl(s)
        if tpl is None:
            paras.append(sentence + ".")
        elif tpl:
            paras.append(fill(tpl, {"name": name, "kind": "a public body" if s == "PublicBody" else "an organization",
                                    "country": e(country(ctry)) if ctry else "", "posts": str(len(posts) or "")}))
    derived = [d for d in p["lead"] if DERIVED.search(d)]
    paras += [e(d) for d in p["lead"] if d not in derived]
    note = "".join(f"<p class=meta>Note: {e(d)}</p>" for d in derived)
    return "".join(f"<p>{x}</p>" for x in paras) + note


def infobox(p, c: Ctx) -> str:
    rows, used = [], {"gender", "keywords"}
    row = lambda label, html_: rows.append(f"<tr><th>{e(label)}</th><td>{html_}</td></tr>") if html_ else None
    link = lambda u: f"<a href='{e(u)}' rel=noreferrer>{e(_url_label(u))}</a>"      # a web address as its site or page, not the whole URL
    val = lambda v: (c.a(v) if v.get("h") or v.get("red") or v.get("unresolved")
                     else link(v["value"]) if re.match(r"https?://\S+$", str(v.get("value") or ""))
                     else e(dates.show(v["value"], v.get("approx")))) + c.sup(v["cites"])
    vals = lambda prop: "<br>".join(val(v) for v in c.values(p, prop))
    disputed = lambda prop: " <span class=disputed title='sources disagree'>(disputed)</span>" \
        if prop in p.get("disagree", []) and len(c.values(p, prop)) > 1 else ""
    s = p["schema"]
    if s == c.reg.roles.PERSON:
        born = vals("birthDate")
        place = c.values(p, "birthPlace")
        row("Born", born + disputed("birthDate") + ("<br>" + "<br>".join(val(v) for v in place) if place else ""))
        b, d = year(c.first(p["body"], "birthDate")), year(c.first(p["body"], "deathDate"))
        age = f" (aged {d - b - 1}–{d - b})" if b and d else ""
        row("Died", vals("deathDate") + disputed("deathDate") + e(age))
        row("Nationality", "<br>".join(country_html(v["value"]) + c.sup(v["cites"])
                                     for v in (c.values(p, "nationality") or c.values(p, "citizenship"))))
        for label, html_ in group_rows(p, c):          # groups.yaml: a house, a party
            row(label, html_)
        spouses = [s for s, _ in c.spouses(p) if s]
        if spouses:
            row("Spouses" if len(spouses) > 1 else "Spouse",
                "<br>".join(c.a(s) for s in spouses[:6])
                + (f"<br><a href='#issue'>all {len(spouses)}</a>" if len(spouses) > 6 else "")
                + ("<div class=meta>by shared children</div>" if not c.stated_spouses(p) else ""))
        kids = c.children(p)
        if kids:
            row("Issue", f"<a href='#issue'>{len(kids)} recorded</a>")
        par = c.parents(p)
        for k in ("father", "mother"):
            if k in par:
                row(k.capitalize(), c.a(par[k]["other"]) + c.sup(par[k]["cites"]))
        offices = _offices(p, c)
        if offices:
            row("Offices", "<br>".join(f"{c.a(r)} <span class=meta>{e(span(r.get('startDate') or r.get('date'), r.get('endDate'), r.get('approx')))}</span>"
                                       for r in offices[-4:]) + (f"<br><a href='#offices'>all {len(offices)}</a>" if len(offices) > 4 else ""))
        row("Title", vals("position"))
        used |= {"birthDate", "deathDate", "birthPlace", "nationality", "citizenship", "position"}
    elif s == c.reg.roles.POST:
        row("Body", vals("organization"))
        terms = c.holders(p["body"])
        if terms:
            first = year(terms[0].get("startDate") or terms[0].get("date"))
            row("First holder", c.a(terms[0]["other"]) + c.sup(terms[0]["cites"])
                + (f" <span class=meta>from {first}</span>" if first else ""))
            last = terms[-1]
            row("Incumbent" if c.incumbent(last) else "Latest recorded", c.a(last["other"]) + c.sup(last["cites"])
                + (f" <span class=meta>since {year(last.get('startDate') or last.get('date'))}</span>" if c.incumbent(last) else ""))
            if first:
                row("Established", f"{first} <span class=meta>or earlier</span>")
            lengths = [(year(r.get("endDate")) - year(r.get("startDate") or r.get("date")), r) for r in terms
                       if year(r.get("endDate")) and year(r.get("startDate") or r.get("date"))]
            if len(lengths) > 1:
                n, r = max(lengths, key=lambda x: x[0])
                row("Longest-serving", f"{c.a(r['other'])} <span class=meta>({n} years)</span>")
            row("Holders", f"<a href='#holders'>{len({r['other'] for r in terms})}</a>")
        row("Country", "<br>".join(country_html(v["value"]) for v in c.values(p, "country")))
        used |= {"organization", "country"}
    elif s == c.reg.roles.EVENT:
        row("Date", vals("date"))
        row("Country", "<br>".join(country_html(v["value"]) for v in c.values(p, "country")))
        used |= {"date", "country", "amount", "currency"}          # the price row comes from deals.py
    elif hschema.is_a(s, "LegalEntity"):
        row("Country", "<br>".join(country_html(v["value"]) for v in c.values(p, "country")))
        posts = _posts_in(p, c)
        if posts:
            row("Positions", f"<a href='#positions'>{len(posts)}</a>")
        row("Part of", "<br>".join(f"{c.a(r)}{c.sup(r['cites'])}" for r in c.rels(p, "Membership", "source")))
        used |= {"country"}
    if s != c.reg.roles.PERSON:                                  # a Person's group rows sit under its nationality
        for label, html_ in group_rows(p, c):
            row(label, html_)
    for extra in INFOBOX_EXTRA:                        # rows another module adds (deals.py: owners, price)
        for label, html_ in extra(p, c):
            row(label, html_)
    if p.get("keys"):                                  # a property holding a key is shown under Identifiers
        from hydra import keys as hkeys
        used |= set(hkeys.by_property(c.wiki.keyconf))
    pdefs = hschema.resolve(s)["props"] if s in hschema.SCHEMA else {}
    featured = list((hschema.resolve(s).get("featured") or [])) if s in hschema.SCHEMA else []
    rank_of = lambda b: featured.index(b["prop"]) if b["prop"] in featured else len(featured)
    def typed(b, v):                                   # a coded value (country, currency, language...) by its standard's name
        kind = STD.kind_of(s, b["prop"], (pdefs.get(b["prop"]) or {}).get("type"))
        if not kind or v.get("h"):
            return val(v)
        label, code = coded(kind, v["value"]), str(v["value"])
        plain = kind == "country" or label.casefold() == code.casefold()     # a country by name; others name (code)
        shown = country_html(code) if kind == "country" else e(label)
        return (shown if plain else f"{e(label)} <span class=meta>({e(code)})</span>") + c.sup(v["cites"])
    for box in sorted(p["infobox"], key=rank_of):      # any schema: its featured properties first, each shown by its type
        if box["prop"] not in used:
            row(box["label"], "<br>".join(typed(box, v) for v in box["values"]))
    if p.get("rank"):
        row("Rank", e(p["rank"]["name"]) + (f" <span class=meta>({e(p['rank']['tier'])})</span>" if p["rank"].get("tier") else ""))
    if p.get("badge") and p["badge"] not in icons.SCHEMA_TOKENS:   # a schema's own token is the domain chip, not a status
        from hydra.wiki import chips
        labels = {**chips.BADGES, **(c.wiki.conf.get("badges") or {})}
        token = p["badge"]
        label = country(token[5:]) if token.startswith("flag-") else \
            (labels[token] if token in labels else token.replace("-", " ").capitalize())
        if label:
            row("Status", e(label))
    if p["aliases"]:
        row("Also known as", "<br>".join(e(a) for a in p["aliases"]))
    img = cycle(c, p) + dbadges.circles(c.wiki, p, c)
    return (f"<table class=infobox><caption>{e(p['title'])}</caption>{img}"
            f"<tr><td colspan=2 class=type>{e(type_label(s))}</td></tr>{''.join(rows)}</table>")


def _length(start, end) -> str:
    if not (start and end):
        return ""
    n = end - start
    return f"{n} year{'s' if n != 1 else ''}" if n else "under a year"


def _neighbours(p, r, c: Ctx) -> tuple:
    """(predecessor, successor) of this person's term `r`, in the post's dated order."""
    order = [x for x in c.holders(r["other"]) if year(x.get("startDate") or x.get("date") or x.get("endDate"))]
    i = next((k for k, x in enumerate(order) if x["other"] == p["body"]
              and x.get("startDate") == r.get("startDate") and x.get("endDate") == r.get("endDate")), None)
    if i is None:
        return None, None
    prev = next((x["other"] for x in reversed(order[:i]) if x["other"] != p["body"]), None)
    nxt = next((x["other"] for x in order[i + 1:] if x["other"] != p["body"]), None)
    return prev, nxt


def offices(p, c: Ctx) -> str:
    terms = _offices(p, c)
    if not terms:
        return ""
    out = ["<h2 id=offices>Offices held</h2><table class=wikitable><tr><th>Office</th><th>Term</th>"
           "<th>Time in office</th></tr>"]
    for r in terms:
        start, end = year(r.get("startDate") or r.get("date")), year(r.get("endDate"))
        rec = r.get("role") or next((n for n in r.get("notes") or [] if n.startswith("Recorded as")), "")
        term = e(span(r.get("startDate") or r.get("date"), r.get("endDate"), r.get("approx"))) or "<span class=meta>no dates</span>"
        if start and not end and c.incumbent(r) and c.is_latest(p["body"], r):
            term += " <span class=meta>(incumbent)</span>"
        out.append(f"<tr><td>{c.a(r)}{c.sup(r['cites'])}"
                   f"{'<div class=meta>' + e(rec) + '</div>' if rec else ''}</td>"
                   f"<td>{term}</td><td>{e(_length(start, end))}</td></tr>")
    return "".join(out) + "</table>"


def succession(p, c: Ctx) -> str:
    """Wikipedia's succession boxes: preceded by | the office, years | succeeded by,
    one per dated term, at the foot of the page."""
    rows = []
    for r in _offices(p, c):
        if not r.get("other") or not year(r.get("startDate") or r.get("date") or r.get("endDate")):
            continue
        prev, nxt = _neighbours(p, r, c)
        if not (prev or nxt):
            continue
        when = e(span(r.get("startDate") or r.get("date"), r.get("endDate"), r.get("approx")))
        last = c.is_latest(p["body"], r)
        life = lambda b: "" if not b or (c.page(b) or {}).get("qualifier") else e(c.life(b))   # a qualifier already dates it
        right = c.a(nxt) if nxt else ("<i>Incumbent</i>" if last and c.incumbent(r) else "<span class=meta>not recorded</span>")
        rows.append(f"<tr><td>{('Preceded by<br>' + c.a(prev)) if prev else '<span class=meta>first recorded</span>'}"
                    f"<div class=meta>{life(prev)}</div></td>"
                    f"<td class=mid><b>{c.a(r)}</b><br>{when}</td>"
                    f"<td>{('Succeeded by<br>' + right) if nxt else right}"
                    f"<div class=meta>{life(nxt)}</div></td></tr>")
    if not rows:
        return ""
    return f"<h2>Succession</h2><table class=succession>{''.join(rows)}</table>"


def holders(p, c: Ctx) -> str:
    terms = c.holders(p["body"])
    if not terms:
        return ""
    out = ["<h2 id=holders>Officeholders</h2><table class=wikitable><tr><th>No.</th><th></th><th>Name</th>"
           "<th>Took office</th><th>Left office</th><th>Time in office</th><th>Recorded as</th></tr>"]
    n = 0
    for r in terms:
        start, end = year(r.get("startDate") or r.get("date")), year(r.get("endDate"))
        dated = bool(start or end)
        n += dated
        other = c.page(r["other"]) or {}
        pic = image(other, small=True) if other else None
        img = f"<img class=thumb src='{c.L.asset(pic)}' alt=''>" if pic else ""
        rec = r.get("role") or next((x[len("Recorded as: "):] for x in r.get("notes") or [] if x.startswith("Recorded as: ")), "")
        if end:
            left = str(end)
        elif r is terms[-1] and c.incumbent(r):
            left = "<i title='no end date and no death recorded'>Incumbent</i>"
        elif start:
            died = year(c.first(r["other"], "deathDate"))
            left = f"<span class=meta>not recorded{f' (died {died})' if died else ''}</span>"
        else:
            left = "—"
        out.append(f"<tr{' class=current' if 'Incumbent' in left else ''}><td>{n if dated else ''}</td><td>{img}</td><td>{c.a(r)}"
                   f"<div class=meta>{e(c.life(r['other']))}</div></td>"
                   f"<td>{start or '—'}</td><td>{left}</td>"
                   f"<td>{e(_length(start, end))}</td><td class=meta>{e(rec)}{c.sup(r['cites'])}</td></tr>")
    return "".join(out) + "</table>"


def _posts_in(p, c: Ctx) -> list[str]:
    return sorted((b for b in c.wiki.back.get(p["body"], ()) if (c.page(b) or {}).get("schema") == c.reg.roles.POST),
                  key=c.wiki.title)


def positions(p, c: Ctx) -> str:
    posts = _posts_in(p, c)
    if not posts:
        return ""
    out = ["<h2 id=positions>Positions</h2><table class=wikitable><tr><th>Position</th><th>Latest recorded holder</th>"
           "<th>From</th><th>Holders</th></tr>"]
    for b in posts:
        terms = c.holders(b)
        last = terms[-1] if terms else None
        out.append(f"<tr><td>{c.a(b)}</td><td>{c.a(last['other']) if last else '—'}</td>"
                   f"<td>{year(last.get('startDate') or last.get('date')) or '' if last else ''}</td>"
                   f"<td>{len({r['other'] for r in terms})}</td></tr>")
    members = c.rels(p, "Membership", "target")
    if members:
        out.append("</table><h2>Members</h2><ul class=cols>" + "".join(
            f"<li>{c.a(r)} <span class=meta>{e(r.get('role') or '')}</span>{c.sup(r['cites'])}</li>"
            for r in sorted(members, key=lambda r: c.wiki.title(r))) + "</ul>")
        return "".join(out)
    return "".join(out) + "</table>"


def family(p, c: Ctx) -> str:
    par, kids, sibs = c.parents(p), c.children(p), c.siblings(p)
    k = c.wiki.kin
    other_kin = [r for r in p["relations"] if r.get("edge") == c.reg.roles.KIN
                 and not any(k.is_(r["verb"], kk) for kk in kinship.KINDS)]
    if not par and not kids and not sibs and not other_kin:
        return ""
    out = ["<h2 id=family>Family</h2>"]
    if par:
        out.append("<p>" + "; ".join(f"{k.capitalize()}: {c.a(r)}"
                                    f"{' <span class=meta>(' + e(c.life(r['other'])) + ')</span>' if c.life(r['other']) else ''}"
                                    f"{c.sup(r['cites'])}"
                                    for k, r in sorted(par.items(), key=lambda kv: kv[0] != "father")) + "</p>")
    stated = c.stated_spouses(p)
    if stated:
        out.append("<p>Spouse" + ("s" if len(stated) > 1 else "") + ": "
                   + ", ".join(f"{c.a(r)}{' <span class=meta>(' + e(c.life(r['other'])) + ')</span>' if c.life(r['other']) else ''}"
                               f"{c.sup(r['cites'])}" for r in stated) + "</p>")
    for label, group in sibs:
        items = "".join(f"<li>{c.a(r)} <span class=meta>{e(c.life(r['other']))}</span></li>" for r in group)
        out.append(f"<details{' open' if len(group) <= 12 else ''}><summary>{label} ({len(group)})</summary>"
                   f"<ul class=cols>{items}</ul></details>")
    if other_kin:
        out.append("<ul class=rel>" + "".join(f"<li>{e(r['verb'])}: {c.a(r)}{c.sup(r['cites'])}</li>"
                                             for r in other_kin) + "</ul>")
    if kids:
        groups = c.spouses(p)
        named = [s for s, _ in groups if s]
        out.append(f"<h3 id=issue>Issue ({len(kids)})</h3>")
        if named:
            out[-1] = (f"<h3 id=issue>Issue ({len(kids)})"
                       f"{info('Grouped by the other parent.')}</h3>")
        for other, group in groups:
            if not group:
                continue                                    # a stated spouse with no recorded shared child
            if other:
                life = c.life(other)
                head = f"With {c.a(other)}{' <span class=meta>(' + e(life) + ')</span>' if life else ''}"
            else:
                head = "Other parent not recorded" if named else ""
            rows = "".join(f"<tr><td>{c.a(r)}{c.sup(r['cites'])}</td>"
                           f"<td>{e(c.kin(c.page(r.get('other')) or {'body': r.get('other')}, 'son'))}</td>"
                           f"<td>{e(c.life(r.get('other')))}</td></tr>" for r in group)
            out.append((f"<h4>{head} ({len(group)})</h4>" if head else "")
                       + f"<table class='wikitable kin'><tr><th>Name</th><th></th><th>Life</th></tr>{rows}</table>")
    return "".join(out)


def timeline(p, c: Ctx) -> str:
    ev = []
    if p["schema"] == c.reg.roles.PERSON:
        for prop, word in (("birthDate", "Born"), ("deathDate", "Died")):
            for v in c.values(p, prop):
                if year(v["value"]):
                    ev.append((year(v["value"]), word, v["cites"]))
        for r in _offices(p, c):
            s, t = year(r.get("startDate") or r.get("date")), year(r.get("endDate"))
            if s:
                ev.append((s, f"Took office: {c.a(r)}", r["cites"]))
            if t:
                ev.append((t, f"Left office: {c.a(r)}", r["cites"]))
        for r in c.children(p):
            y = year(c.first(r["other"], "birthDate"))
            if y:
                ev.append((y, f"{c.kin(c.page(r['other']) or {'body': r['other']}, 'son').capitalize()} born: {c.a(r)}", r["cites"]))
    elif p["schema"] == c.reg.roles.POST:
        for r in c.holders(p["body"]):
            s = year(r.get("startDate") or r.get("date"))
            if s:
                ev.append((s, f"{c.a(r)} takes office", r["cites"]))
    if len(ev) < 3:
        return ""
    ev.sort(key=lambda x: (x[0], not x[1].startswith("Born"), x[1].startswith("Died")))
    return ("<h2>Timeline</h2>" + "<div class=tlbar><span>Show</span>"
            "<button type=button data-tl=v class=on>Vertical</button><button type=button data-tl=h class=on>Horizontal</button>"
            f"<script>{assets.script('timeline.js')}</script></div>" + "<ul class=timeline>") + "".join(
        f"<li><b>{c.year_link(y)}</b> {txt}{c.sup(ci)}</li>" for y, txt, ci in ev) + "</ul>"


def _recorded(p) -> dict:
    out = defaultdict(list)
    for n in p["notes"]:
        for line in n.splitlines():
            m = NOTE_LINE.match(line.strip())
            if m:
                out[m.group(1)].append(m.group(2))
            elif line.strip():
                out[""].append(line.strip())
    return out


def _linkify(text: str) -> str:
    out, last = [], 0
    for m in URL.finditer(text):
        out.append(e(text[last:m.start()]))
        u = m.group(1)
        out.append(f"<a href='{e(u)}' rel=noreferrer>{e(_url_label(u))}</a>")
        last = m.end()
    out.append(e(text[last:]))
    return "".join(out)


def _url_label(u: str) -> str:
    parts = urllib.parse.urlsplit(u)
    if parts.netloc.endswith("wikipedia.org") and parts.path.startswith("/wiki/"):
        return urllib.parse.unquote(parts.path[6:]).replace("_", " ") + " – Wikipedia"
    return parts.netloc or u


def recorded(p, c: Ctx) -> str:
    rec = _recorded(p)
    if not rec:
        return ""
    rows = "".join(f"<dt>{e(k or 'Note')}</dt>" + "".join(f"<dd>{_linkify(v)}</dd>" for v in vs) for k, vs in rec.items())
    return f"<h2>As recorded{info('Worded exactly as the sources word it.')}</h2><dl class=recorded>{rows}</dl>"


def identifiers(p, c: Ctx) -> str:
    """Outward identifiers the records claim (`upstream: ns:key`), linked by `identifiers:` in wiki.yaml:
    `identifiers: {wikidata: {label: Wikidata, url: "https://www.wikidata.org/wiki/{id}"}}`."""
    out = []
    for v in p.get("upstream") or []:
        hit = c.reg.identifiers.link(v)
        if hit:
            label, url = hit
            out.append((label, url, v))
    if not out:
        return ""
    lis = "".join(f"<li><a href='{e(url)}' rel=noreferrer>{e(label)}: {e(v.split(':', 1)[-1])}</a></li>"
                  for label, url, v in out)
    return f"<h2>Identifiers{info('IDs in other catalogues.')}</h2>" \
           f"<ul class=identifiers>{lis}</ul>"


def references(p, c: Ctx) -> str:
    if not p["citations"]:
        return ""
    out = ["<h2>References</h2><ol class=refs>"]
    by_cite: dict[int, list] = defaultdict(list)             # citation number -> the relationships it supports
    for r in p["relations"]:
        for n in r.get("cites") or ():
            by_cite[n].append(r)
    for ci in p["citations"]:
        first = next((l for l in ci.get("quote", "").splitlines() if l.strip()), "")
        first = AS_RECORDED.sub("", first).strip()
        docs = "; ".join((c.a(d["h"]) if d["h"] in c.wiki.pages else e(d["title"])) for d in ci["docs"])
        bits = []
        if first:
            bits.append(f"“{_linkify(first)}”")
        if docs:
            bits.append(f"<i>{docs}</i>")
        bits += [f"<a href='{e(u)}' rel=noreferrer>{e(_url_label(u))}</a>" for u in ci["urls"] if u not in first]
        where = "" if ci["member"] == "self" else f"{ci['member']}/"
        kind = type_label(ci.get("schema") or "", plural=False).lower() or "record"
        if (hschema.SCHEMA.get(ci.get("schema") or "") or {}).get("edge"):   # a relationship record: say what it says, never its id
            rs = by_cite.get(ci["n"], [])
            what = "; ".join(f"{e(r['verb'])} {c.a(r)}" for r in rs[:3]) + (f" (+{len(rs) - 3} more)" if len(rs) > 3 else "")
            rec = f"<span class=rec title='a relationship these records state'>{what or 'a relationship'}</span>"
        else:
            b = c.wiki.body_of_record(ci["record"])
            who = f"{c.a(b)} · " if b else ""
            rec = (f"<span class=rec title='the record this comes from: {e(where)}{e(ci['record'])}'>"
                   f"{who}a {e(kind)} record</span>")
        out.append(f"<li id='cite-{ci['n']}'>{'. '.join(bits) + ' · ' if bits else ''}{rec}</li>")
    return "".join(out) + "</ol>" + _origin_line(p, c)


def _origin_line(p, c: Ctx) -> str:
    """One quiet line: where this page's citations come from, and how many rest on Wikipedia alone."""
    from hydra import provenance
    seen, n_wiki, n = {}, 0, 0
    for ci in p["citations"]:
        o = provenance._origins(ci, c.wiki.pages)
        if o == ["unsourced"]:
            continue
        n += 1
        n_wiki += all(provenance.is_wiki(x) for x in o)
        for x in o:
            seen[x] = seen.get(x, 0) + 1
    if not n:
        return ""
    by = ", ".join(f"{e(k)} ({v})" for k, v in sorted(seen.items(), key=lambda kv: -kv[1])[:5])
    tail = f" · {n_wiki} of {n} from Wikipedia only" if n_wiki else ""
    link = " · <a href='/sources'>Sources</a>" if not c.L.static else ""
    return f"<p class=meta>Cited from {by}{tail}{link}</p>"


def links(p, c: Ctx) -> str:
    """The page's own records' links, then those of the links it states (a Family
    link's URL is about the child: it shows on the child's page, not the parent's)."""
    own = {m.split("/", 1)[1] for m in p["members"]}
    urls = [u for ci in p["citations"] if ci["record"] in own for u in ci["urls"]]
    urls += [u for r in p["relations"] if r.get("side") == "source" for u in r.get("urls") or []]
    urls = list(dict.fromkeys(urls))
    if not urls:
        return ""
    return "<h2>External links</h2><ul>" + "".join(
        f"<li><a href='{e(u)}' rel=noreferrer>{e(_url_label(u))}</a></li>" for u in urls) + "</ul>"


def groups_of(p, c: Ctx) -> list[tuple[str, dict, str, dict]]:
    """The groups (groups.yaml: a house, a party) a page's record is a member of:
    [(group name, its rules, the organization's page, the relation)], in the file's order."""
    out = []
    for gname, g in c.wiki.groups.items():
        via, match = g.get("via") or "Membership", g.get("match") or {}
        for r in p["relations"]:
            org = r.get("other")
            if r.get("edge") != via or r.get("side") != "source" or org not in c.wiki.pages:
                continue
            title = c.wiki.title(org, qualified=False)
            ok = any(re.search(str(v), title) if k == "name" else
                     str(r.get("role") or "").strip().casefold() == str(v).strip().casefold() if k == "role" else
                     any(str(x.get("value") or "") == str(v) for x in c.values(org, k)) for k, v in match.items())
            if ok and not any(o == org and n == gname for n, _, o, _ in out):
                out.append((gname, g, org, r))
    return out


def group_category(g: dict, c: Ctx, org: str) -> str:
    return str(g.get("category") or "{name}").replace("{name}", c.wiki.title(org, qualified=False))


def group_rows(p, c: Ctx) -> list[tuple[str, str]]:
    """Infobox rows for the groups a page belongs to: the group's label, its organizations linked."""
    by: dict[str, list[str]] = {}
    labels = {}
    for gname, g, org, r in groups_of(p, c):
        labels[gname] = g.get("label") or gname.capitalize()
        by.setdefault(gname, []).append(f"{c.a(org)}{c.sup(r['cites'])}")
    return [(labels[n], "<br>".join(v)) for n, v in by.items()]


def categories(p, c: Ctx) -> list[tuple[str, str]]:
    """-> [(kind, key)]: derived ones first, then type, member, collection."""
    out = []
    if p["schema"] == c.reg.roles.PERSON:
        for prop, kind in (("birthDate", "births"), ("deathDate", "deaths")):
            y = year(c.first(p["body"], prop))
            if y:
                out.append((kind, str(y)))
    out += [("group", group_category(g, c, org)) for _, g, org, _ in groups_of(p, c)]
    if p["schema"] == c.reg.roles.PERSON:
        for r in _offices(p, c):
            if r.get("other"):
                out.append(("office", c.wiki.title(r["other"], qualified=False)))
    out.append(("type", p["schema"]))
    out += [("member", m) for m in sorted({r.split("/", 1)[0] for r in p["members"]})]
    out += [("collection", d) for d in p["datasets"]]
    out += [("universe", u) for u in p["collections"]]
    return list(dict.fromkeys(out))


CAT_LABEL = {"births": "{} births", "deaths": "{} deaths", "group": "{}", "office": "Holders of {}",
             "type": "{}", "member": "Member: {}", "collection": "Collection: {}", "universe": "{}"}

INFOBOX_EXTRA: list = []                         # callables (page, Ctx) -> [(label, html)]
ACTIONS: list = []                               # callables (page, Ctx) -> [{id, label, icon, tip}]: the buttons in the actions box
ACTIONS_SHOWN = 2                                # more than this go under a "more" button, so the box never grows or wraps


def _draft(p, c: Ctx) -> list[dict]:
    tip = "Draft: not wired yet"
    return [{"id": "draft-enrich", "label": "Enrich", "icon": "gem", "tip": tip},
            {"id": "draft-resource", "label": "Re-source", "icon": "landmark", "tip": tip},
            {"id": "draft-portrait", "label": "Fetch portrait", "icon": "user", "tip": tip}]


def draft_actions() -> None:
    """Three sample buttons that do nothing, to see the box and its "more" menu (wiki.yaml `actions_draft: true`)."""
    if _draft not in ACTIONS:
        ACTIONS.append(_draft)


def action_band(p, c: Ctx) -> str:
    """The actions box under the infobox: buttons for working on this entry (enrich, transform...). Live server and
    Editor view only; empty until a module adds to ACTIONS. A button names itself by `id`; nothing here runs it."""
    if c.L is None or c.L.static:
        return ""
    acts = [a for fn in ACTIONS for a in fn(p, c)]
    btn = lambda a: (f"<button type=button class=act data-act='{e(a['id'])}' title='{e(a.get('tip') or a['label'])}'>"
                     f"{icons.svg(c.wiki.root, a.get('icon') or '', 14)}<span>{e(a['label'])}</span></button>")
    more = (f"<details class=more><summary title='More actions'>⋯</summary><div>{''.join(map(btn, acts[ACTIONS_SHOWN:]))}</div></details>"
            if len(acts) > ACTIONS_SHOWN else "")
    return (f"<div class='widget{'' if acts else ' m-only empty'}'><div class=wlabel>Actions</div><div class=row>"
            f"{''.join(map(btn, acts[:ACTIONS_SHOWN]))}{more}</div></div>")


# the body sections by name (visuals.py adds its own); a name is what wiki.yaml `sections:` uses
SECTIONS = {f.__name__: f for f in (offices, holders, positions, family, timeline, recorded, identifiers)}  # visuals.py and deals.py add theirs

METHODS = {                                       # keyed by a schema; a schema without an entry takes its nearest ancestor's
    roles.PERSON: ("offices", "holdings", "acted_for", "family", "ancestors", "timeline", "lifebar", "recorded"),   # the list before the bar, so it fills the space beside the infobox
    roles.POST: ("holders", "timeline", "recorded"),
    roles.EVENT: ("parties", "recorded"),
    "LegalEntity": ("positions", "holdings", "owners", "acted_for", "deals", "recorded"),
    "Asset": ("provenance", "owners", "deals", "recorded"),
    "Thing": ("recorded",),
}


def methods_for(schema: str, conf: dict | None = None) -> tuple:
    """The section functions a page gets, in order: the schema's own entry, else its nearest ancestor's
    (Vessel -> Vehicle -> Asset), and wiki.yaml `sections: {Schema: [names]}` over any of them.
    A role renamed in wiki.yaml (`roles: {post: Office}`) still takes its role's sections."""
    given = (conf or {}).get("sections") or {}
    r = Roles((conf or {}).get("roles"))
    canon = {r.PERSON: "Person", r.POST: "Position", r.EVENT: "Event"}
    names = next((given.get(n) or METHODS.get(canon.get(n, n)) for n in hschema.ancestors(schema) or (schema,)
                  if given.get(n) or METHODS.get(canon.get(n, n))), METHODS["Thing"])
    return tuple(SECTIONS[n] for n in names if n in SECTIONS)
