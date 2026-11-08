"""site.py — a small Wikipedia-shaped reader over `universe/.parsed/`.

    serve   a local preview (stdlib http.server), searching server side
    site    static HTML: one file per H, plus a search page that reads search.json

It reads only the build's output, never a member or the H-table, so it shows
exactly what the last build decided and the same on a folder or a `.hydra`.

    URL           /e/<body>        never changes with state or flags; a full H
                                   (`/e/H-d4-...`) answers 301 to its body
    redirect      flag 8           301 to the H it was merged into
    tombstone     flag 1           410: the H is kept, its records are gone
    banners       flags 4, 2       needs re-review; sources disagree
                  no sources       the page's records cite no document and no link
                  facts            the archive build's facts.* findings on its records
    name page     /n/<name>        every page with one title ("may refer to"); search goes there
    year page     /y/<year>        births, deaths, offices taken and left; /years lists them
"""
from __future__ import annotations

import datetime
import difflib
import html
import json
import re
import shutil
import urllib.parse
from collections import Counter, defaultdict
from functools import cached_property, lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hydra.identity import types as htypes

from hydra import layout, schema as hschema
from hydra.universe import hid
from hydra.universe import layer as U
from hydra.wiki import assets, badges, chips, declared, deals, flags, icons, idents, landing, panel, roles, views, visuals  # noqa: F401  (deals, idents add sections and rows)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", html.unescape(text).lower()).strip("-")


def _plural(word: str) -> str:
    """An English plural for a section or verb: "Family" -> "Families", "member of" -> "members"."""
    w = word.strip()
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    return w[:-1] + "ies" if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou" else w + "s"

e = html.escape


def _prop(p, name: str) -> str:
    """The first value an entry's infobox holds for a property ("" when it has none)."""
    for row in p.get("infobox") or ():
        if row.get("prop") == name and row.get("values"):
            return str(row["values"][0].get("value") or "")
    return ""


def _source_line(p) -> str:
    """What tells one kept document from another in a list: who published it, and when it was retrieved."""
    got = _prop(p, "retrievedAt")
    try:
        got = f"retrieved {datetime.date.fromisoformat(got[:10]).strftime('%d %b %Y').lstrip('0')}"
    except ValueError:
        got = f"retrieved {got}" if got else ""
    return " · ".join(x for x in (_prop(p, "publisher"), got) if x)

# A theme is colours and a few shapes. Body text is always `ink`: colour is for links (close to the ink),
# for small accents (icons, bars, chips) and for the header, never for ordinary text.
_SANS = "system-ui,-apple-system,'Segoe UI',sans-serif"
_CLASSIC = {"panel": "var(--soft)", "accent": "var(--link)", "accent2": "var(--warnline)", "headink": "var(--ink)",
            "radius": "4px", "shadow": "none", "serif": "var(--sans)", "sans": _SANS, "tint": "var(--head)",
            "th": "var(--head)"}
# `th`: the light surface of table headers, bars and bands (not the header: in dune that one is dark)
_SHORE = {"accent": "#c87a4f", "accent2": "#e89b68", "red": "#b2452b", "radius": "12px", "sans": _SANS, "th": "var(--soft)",
          "serif": "var(--sans)"}
THEMES = {
    "shore": {**_SHORE, "bg": "#fbf8f5", "ink": "#1d2624", "muted": "#6b7471", "line": "#e7dcd4", "soft": "#f6efe9",
              "head": "#ffffff", "headink": "#1d2624", "link": "#0f4a44", "visited": "#2a6560", "warn": "#fbeee4",
              "warnline": "#d98a58", "chip": "#eef2f4", "chip_c": "#f9e2d2", "chip_d": "#dcebe8", "input": "#ffffff",
              "panel": "#ffffff", "tint": "#f9ece4", "shadow": "0 1px 2px rgba(15,74,68,.05),0 4px 14px rgba(15,74,68,.04)"},
    "dune": {**_SHORE, "bg": "#f6ede7", "ink": "#22201d", "muted": "#74675f", "line": "#e6d2c6", "soft": "#f1e3da",
             "head": "#fffaf7", "headink": "#22201d", "link": "#1b5e52", "visited": "#3d6f66", "warn": "#f9e6d8",
             "warnline": "#c87a4f", "chip": "#efe0d6", "chip_c": "#f6d7c2", "chip_d": "#d7e7e3", "input": "#fffaf7",
             "panel": "#fffaf7", "tint": "#e6b9a6", "shadow": "0 1px 3px rgba(60,35,20,.06)"},
    "tide": {**_SHORE, "bg": "#f3f6f8", "ink": "#1b2427", "muted": "#64727a", "line": "#d6e1e7", "soft": "#eaf0f3",
             "head": "#ffffff", "headink": "#1b2427", "link": "#1f5d57", "visited": "#2a7570", "warn": "#fbefe6",
             "warnline": "#e89b68", "chip": "#e3ebef", "chip_c": "#f8e1d1", "chip_d": "#d9ebe8", "input": "#ffffff",
             "panel": "#ffffff", "tint": "#d6e1e7", "radius": "8px", "serif": "var(--sans)",
             "shadow": "0 1px 2px rgba(27,36,39,.05)"},
    "tan": {**_CLASSIC, "bg": "#f7f1e5", "ink": "#2e2619", "muted": "#6e604b", "line": "#cbbb9b", "soft": "#efe5d1",
            "head": "#e6d8bb", "link": "#8a4a12", "visited": "#6d3c14", "red": "#b3341f", "warn": "#f6e4bd",
            "warnline": "#c8902a", "chip": "#e3d3b2", "chip_c": "#f3dfb2", "chip_d": "#d6e3c3", "input": "#fbf7ef"},
    "light": {**_CLASSIC, "bg": "#ffffff", "ink": "#202122", "muted": "#54595d", "line": "#a2a9b1", "soft": "#f8f9fa",
              "head": "#eaecf0", "link": "#3366cc", "visited": "#6b4ba1", "red": "#d73333", "warn": "#fef6e7",
              "warnline": "#ffcc33", "chip": "#eaecf0", "chip_c": "#fff3cd", "chip_d": "#d5fdf4", "input": "#ffffff"},
}
DEFAULT_THEME = "dune"

# Each palette theme's dark mode: the same accents, lightened to read on a dark ground; text plain and light.
_DARK = {"red": "#e07a63", "warnline": "#c87a4f", "accent": "#e09a6f", "accent2": "#e8a87a",
         "shadow": "0 1px 2px rgba(0,0,0,.35)"}
DARK = {
    "shore": {**_DARK, "bg": "#121a19", "ink": "#e9e3dd", "muted": "#9aa5a1", "line": "#2b3734", "soft": "#1e2a27",
              "head": "#141e1c", "headink": "#e9e3dd", "link": "#86c9bd", "visited": "#a3d3ca", "warn": "#2f231a",
              "chip": "#243330", "chip_c": "#3b2b21", "chip_d": "#1f3733", "input": "#18221f", "panel": "#18221f",
              "tint": "#1d2b28"},
    "dune": {**_DARK, "bg": "#141618", "ink": "#ece8e3", "muted": "#9a9fa3", "line": "#2c3135", "soft": "#1e2225",
             "head": "#1b2022", "headink": "#ece8e3", "link": "#84c7bb", "visited": "#a3cfc6", "warn": "#29282a",
             "chip": "#252a2d", "chip_c": "#2e2c29", "chip_d": "#1f302d", "input": "#191c1e", "panel": "#1a1d20",
             "tint": "#222a29", "wash": "#8fa3b8",
             "accent": "#9db4cc", "accent2": "#d9b872", "warnline": "#d9b872"},
    "tide": {**_DARK, "bg": "#11171d", "ink": "#e3e9ee", "muted": "#93a3ad", "line": "#2a3540", "soft": "#1d2731",
             "head": "#161e26", "headink": "#e3e9ee", "link": "#7fc6bc", "visited": "#9fd3cb", "warn": "#2e241c",
             "chip": "#222d38", "chip_c": "#3a2c22", "chip_d": "#1d3533", "input": "#18212a", "panel": "#18212a",
             "tint": "#1f2c37"},
}


def _vars(t: dict) -> str:
    return "".join(f"--{k.replace('_', '-')}:{v};" for k, v in t.items())


FONT_KEYS = {"heading": "serif", "body": "sans"}       # wiki.yaml theme.fonts -> the variables they set


def theme_name(conf: dict | None, asked: str | None = None) -> str:
    """The theme in use: the one asked for (`--theme`), else wiki.yaml `theme.base`, else the default."""
    base = ((conf or {}).get("theme") or {}).get("base") if isinstance((conf or {}).get("theme"), dict) else None
    for name in (asked, base, DEFAULT_THEME):
        if name in THEMES:
            return name
    return DEFAULT_THEME


def css(theme: str = DEFAULT_THEME, custom: dict | None = None) -> str:
    """The theme's variables, then the stylesheet."""
    return theme_vars(theme, custom) + "\n" + assets.text("wiki.css")


def theme_vars(theme: str = DEFAULT_THEME, custom: dict | None = None) -> str:
    """The theme's colours; with a dark mode, used when the system asks for dark (unless the reader chose
    light) or when the reader chose dark (`data-mode` on <html>, set by the header switch or ?mode=).
    `custom`: wiki.yaml `theme:` over it: `fonts` {heading, body}, `radius`, and any variable under
    `light` / `dark` (bg, ink, muted, line, soft, panel, head, headink, link, accent, accent2, tint...).
    The review page takes these alone: it has its own stylesheet."""
    name = theme if theme in THEMES else DEFAULT_THEME
    c = custom if isinstance(custom, dict) else {}
    shared = {FONT_KEYS[k]: v for k, v in (c.get("fonts") or {}).items() if k in FONT_KEYS and v}
    if c.get("radius"):
        shared["radius"] = c["radius"]
    light = {**THEMES[name], **shared, **{k: v for k, v in (c.get("light") or {}).items() if v}}
    out = ":root{" + _vars(light) + "color-scheme:light}\n"
    if name in DARK or c.get("dark"):
        dark = _vars({**light, **DARK.get(name, {}), **shared, **{k: v for k, v in (c.get("dark") or {}).items() if v}})
        dark += "color-scheme:dark"
        out += (f"@media (prefers-color-scheme:dark){{:root:not([data-mode=light]){{{dark}}}}}\n"
                f":root[data-mode=dark]{{{dark}}}\n")
    return out


# Moving between pages fades; the opt-in must be inline: in wiki.css it can arrive after the page is first revealed, and the
# browser then skips the fade ("ViewTransition opt-in disabled"). The menu column stays where it is.
VT = ("@view-transition{navigation:auto}header.site{view-transition-name:menu}"
      "::view-transition-group(*),::view-transition-old(*),::view-transition-new(*){animation-duration:.12s}"
      "@media (prefers-reduced-motion:reduce){::view-transition-group(*),::view-transition-old(*),::view-transition-new(*){animation:none}}")

FLAG_TEXT = {"stale": "A decision about this entity was made on different records than it holds now: it needs re-review.",
             "conflict": "Its sources disagree about {what}.",
             "orphaned": "No member holds its records any more."}


class Links:
    """Where a link goes: the live server's routes, or the static site's flat files."""

    def __init__(self, static: bool):
        self.static = static

    def page(self, body):
        return f"e-{body}.html" if self.static else f"/e/{body}"

    def talk(self, body):
        return f"talk-{body}.html" if self.static else f"/talk/{body}"

    def cat(self, kind, key):
        return f"c-{kind}-{re.sub(r'[^A-Za-z0-9_.-]', '_', key)}.html" if self.static \
            else f"/c/{kind}/{urllib.parse.quote(key, safe='')}"

    def home(self):
        return "index.html" if self.static else "/"

    def search(self):
        return "search.html" if self.static else "/search"

    def name(self, key):
        return f"n-{_slug(key)}.html" if self.static else f"/n/{urllib.parse.quote(key, safe='')}"

    def year(self, y):
        return f"y-{y}.html" if self.static else f"/y/{y}"

    def years(self):
        return "years.html" if self.static else "/years"

    def browse(self):                            # the static site has no browse page: the index stands in
        return "index.html" if self.static else "/browse"

    def asset(self, rel):
        return rel if self.static else f"/{rel}"

    def change(self, sid):                       # a change's review page: the live wiki only
        return None if self.static else f"/changes/{sid}"

    def changes(self):
        return None if self.static else "/changes"


class Wiki:
    def __init__(self, root, states=("c", "p", "d")):
        self.root = Path(root)
        hschema.load(self.root)
        self.pages = {p["body"]: p for p in U.read_parsed(root, "pages.jsonl") if p["state"] in states}
        # in scope (scope.yaml): listed and linked. Context pages still open at their address,
        # but are named as text elsewhere and listed nowhere
        self.listed = {b for b, p in self.pages.items() if (p.get("scope") or {}).get("in", True)}
        self.canon = {r["body"]: r for r in U.read_parsed(root, "canon.jsonl")}
        self.report = U.read_parsed(root, "report.json")
        self.conf = self._conf()
        from hydra.wiki import conf as wconf, reg as wreg
        self.coll_conf = wconf.collection_conf(self.root, self.conf)
        self.reg = wreg.Reg(self.conf)
        self.regs = {name: wreg.Reg(c) for name, c in self.coll_conf.items()}
        _ = self.kin, self.keyconf, self.vocab, self.capacity, self.groups
        roles.configure(self.conf.get("roles"))
        declared.register(self.conf.get("define"))
        flags.configure(self.conf.get("flags"))
        if self.conf.get("actions_draft"):
            views.draft_actions()
        icons.configure(self.conf.get("icons"))
        badges.configure(self.conf.get("badge_rules"), self.conf.get("derived_badges", True))
        views.configure_lead(self.conf.get("lead"))
        self.search_rows = [r for r in U.read_parsed(root, "search.json") if r["b"] in self.pages]
        self.back = defaultdict(set)
        self.back_by = defaultdict(lambda: defaultdict(set))       # page -> {the field that names it: the pages naming it}
        for b, p in self.pages.items():
            for box in p["infobox"]:
                for v in box["values"]:
                    if v.get("h") and v["h"] != b:
                        self.back[v["h"]].add(b)
                        self.back_by[v["h"]][box.get("label") or box["prop"]].add(b)
        self.names = defaultdict(list)          # a name as searched -> every page with that title
        for b, p in sorted(self.pages.items(), key=lambda kv: kv[1]["title"]):
            if b in self.listed:
                self.names[self.name_key(p["title"])].append(b)
        self.tx = defaultdict(list)             # deal body -> [(page body, relation)]: records that name it, at their source end
        for b, p in self.pages.items():
            for r in p["relations"]:
                if r.get("side") == "source":
                    for t in deals.deals_of(r):
                        self.tx[t].append((b, r))
        self.by_key = {f"{k['ns']}:{k['key']}": b for b, p in self.pages.items() for k in p.get("keys") or ()}
        from hydra import standards
        views.STD = standards.load(self.root)           # this archive's labels and demonyms over ISO's
        self.years = self._years()
        self.facts = self._facts()
        self.cats = defaultdict(set)
        self.page_cats = {}
        for b, p in self.pages.items():
            self.page_cats[b] = views.categories(p, views.Ctx(self, None, p))
            for kind, key in self.page_cats[b] if b in self.listed else ():
                self.cats[(kind, key)].add(b)
            if b in self.listed:
                self.cats[("type", p["schema"])].add(b)   # /c/type/<schema>: every entry of a kind

    def first(self, body, prop):
        """A page's first value of a property (a date, an amount): the value, or its H."""
        for box in (self.pages.get(body) or {}).get("infobox") or []:
            if box["prop"] == prop and box["values"]:
                v = box["values"][0]
                return v.get("value") or v.get("h")
        return None

    @property
    def capacity(self) -> dict:
        """.hydra/rules/capacity.yaml: the archive's own, else the one hydra ships."""
        if not hasattr(self, "_capacity"):
            import yaml
            from hydra import resources
            f = self.root / layout.CAPACITY
            f = f if f.is_file() else resources.TEMPLATE / layout.CAPACITY
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else None
            self._capacity = doc if isinstance(doc, dict) else {}
        return self._capacity

    def _rules(self, rel: str) -> dict:
        """A rules file: the archive's own, else the one hydra ships; {} when neither parses."""
        import yaml
        from hydra import resources
        f = self.root / rel
        f = f if f.is_file() else resources.TEMPLATE / rel
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else None
        return doc if isinstance(doc, dict) else {}

    @cached_property
    def kin(self):
        """.hydra/rules/kinship.yaml: what each Family word says."""
        from hydra import kinship
        return kinship.load(self.root)

    @property
    def groups(self) -> dict:
        """.hydra/rules/groups.yaml `groups`: {name: {label, via, match, category, box}}."""
        if not hasattr(self, "_groups"):
            g = self._rules(layout.GROUPS).get("groups") or {}
            self._groups = {str(k): v for k, v in g.items() if isinstance(v, dict)}
        return self._groups

    def body_of_record(self, rid: str):
        """A record id as a collection writes it (`hrs-frankel`, or `saud:hrs-frankel`) -> its page, or None."""
        if not hasattr(self, "_rec_body"):
            idx = {}
            for b, row in self.canon.items():
                if row.get("redirect"):
                    continue
                for m in row.get("members") or ():
                    ref = m.split("/", 1)[-1]
                    idx.setdefault(ref, b)
                    idx.setdefault(ref.split(":", 1)[-1], b)
            self._rec_body = idx
        return self._rec_body.get(rid) or self._rec_body.get(str(rid).split(":", 1)[-1])

    def render_change(self, L: Links, sid: str) -> str:
        """One change, to review: what it did, and every record it added, corrected or removed, linked."""
        from hydra import history
        try:
            d = history.describe(self.root, history.resolve(self.root, sid))
        except SystemExit:
            return self.frame(L, "No such change", "<h1>No such change</h1>")
        title = d["message"] or d["headline"]
        out = [f"<h1>{e(title)}</h1>", f"<p class=meta>{e(d['time'][:16].replace('T', ' '))} UTC"
               + (f" · {e(d['author'])}" if d["author"] else "") + f" · change <code>{e(d['sid'][:12])}</code>"
               + (f" · {d['squashed']} steps combined" if d.get("squashed") else "") + "</p>"]
        if d["message"]:
            out.append(f"<p>{e(d['headline'])}.</p>")

        from hydra import schema as hschema
        hschema.ensure()
        parent = (history.snap(self.root, d["sid"])["parents"] or [None])[0]

        def end(v):                              # a link value (an id, or a name one page has): that page, else the text
            named = self.names.get(self.name_key(v)) or []
            b = self.body_of_record(v) or (named[0] if len(named) == 1 else None)
            return self.a(L, b) if b else e(v)

        def say(rid, rec):
            """An entity record: its page. A relationship: "Ownership: owner → asset", both ends linked."""
            b = self.body_of_record(rid)
            s = (rec or {}).get("schema", "")
            edge = (hschema.SCHEMA.get(s) or {}).get("edge")
            if edge and rec:
                p = rec.get("properties") or {}
                src, tgt = (", ".join(end(v) for v in p.get(k) or []) or "?" for k in (edge["source"], edge["target"]))
                word = (p.get("relationship") or p.get("role") or [""])[0]
                return (f"<span class=meta>{e(hschema.SCHEMA[s].get('label') or s)}:</span> {src} → {tgt}"
                        + (f" <span class=meta>({e(word)})</span>" if word else ""))
            if b:
                return f"{self.a(L, b)} <span class=meta>{e(self.type_label(self.pages[b]['schema']) if b in self.pages else s)}</span>"
            name = ((rec or {}).get("properties") or {}).get("name") or [rid]
            return f"{e(name[0])} <span class=meta>{e(s)}, no page</span>"

        def items(ids, recs):
            rows = sorted(ids, key=lambda r: (bool((hschema.SCHEMA.get((recs.get(r) or {}).get("schema", "")) or {}).get("edge")), r))
            return "<ul class=changes>" + "".join(f"<li>{say(r, recs.get(r))}</li>" for r in rows[:400]) + "</ul>" + \
                (f"<p class=meta>and {len(ids) - 400} more.</p>" if len(ids) > 400 else "")
        for c in d["collections"]:
            now, before = history.records_at(self.root, d["sid"], c["path"]), history.records_at(self.root, parent, c["path"])
            out.append(f"<h2>{e(c['name'])}</h2>")
            for key, label, recs in (("added", "Added", now), ("changed", "Corrected", now), ("removed", "Removed", before)):
                if c[key]:
                    out.append(f"<h3>{label} <span class=meta>({len(c[key])})</span></h3>" + items(c[key], recs))
        if d["published"]:
            out.append(f"<h2>Ids made permanent <span class=meta>({len(d['published'])})</span></h2><ul class=cols>"
                       + "".join(f"<li>{self.a(L, b) if b in self.pages else e(b)}</li>" for b in d["published"][:300]) + "</ul>")
        if d["decisions"]:
            out.append(f"<h2>Review decisions <span class=meta>({len(d['decisions'])})</span></h2><ul class=cols>"
                       + "".join(f"<li><code>{e(str(k))}</code></li>" for k in d["decisions"][:300]) + "</ul>")
        if d["settings"]:
            out.append("<h2>Settings changed</h2><p>" + ", ".join(f"<code>{e(s)}</code>" for s in d["settings"]) + "</p>")
        out.append(f"<p class=meta>Full diff: <code>hydra-ctl history diff {e(d['sid'][:12])}~1 "
                   f"{e(d['sid'][:12])}</code>. <a href='{L.changes()}'>All history</a></p>")
        return self.frame(L, title, "".join(out))

    @property
    def provenance(self) -> dict:
        if not hasattr(self, "_prov"):
            from hydra import provenance
            self._prov = provenance.report(self.root, top=40)
        return self._prov

    @cached_property
    def source_catalog(self):
        from hydra.wiki import sourcebrowser
        return sourcebrowser.catalog(self)

    @staticmethod
    def stack(w: int, o: int, n: int, cls: str = "") -> str:
        """A bar of records: resting on Wikipedia alone, on other sources, on none."""
        t = (w + o + n) or 1
        seg = lambda k, v, label: f"<i class={k} style='width:{v / t * 100:.2f}%' title='{label}: {v:,}'></i>" if v else ""
        return f"<span class='stack {cls}'>{seg('w', w, 'Wikipedia only')}{seg('o', o, 'Other sources')}{seg('n', n, 'No source')}</span>"

    def render_collections(self, L: Links) -> str:
        """The archive by collection: what each holds and how well it is sourced."""
        sourced = {c["collection"]: c for c in self.provenance["collections"]}
        rows = []
        for (kind, key), bodies in self.cats.items():
            if kind != "collection":
                continue
            name = key.partition("/")[2].removeprefix("sources/") or key
            kinds = Counter(self.pages[b]["schema"] for b in bodies)
            held = ", ".join(f"{n:,} {e(self.type_label(s, plural=n != 1).lower())}" for s, n in kinds.most_common(3))
            if len(kinds) > 3:
                held += f", {len(kinds) - 3} more kinds"
            s = sourced.get(name) or {}
            bar = self.stack(s.get("wikipedia_only", 0), s.get("citations", 0) - s.get("wikipedia_only", 0), s.get("unsourced", 0)) if s else ""
            rows.append((len(bodies), f"<tr><td><a href='{L.cat(kind, key)}'>{e(name)}</a></td><td class=num>{len(bodies):,}</td>"
                                      f"<td class=meta>{held}</td><td>{bar}</td></tr>"))
        if not rows:
            return self.frame(L, "Collections", "<h1>Collections</h1><p class=meta>This archive has no collections.</p>")
        body = "".join(r for _, r in sorted(rows, key=lambda x: -x[0]))
        return self.frame(L, "Collections", "<h1>Collections</h1><section class=panel><table class=list>"
                                            "<tr><th>Collection</th><th>Entries</th><th>Entry types</th><th>Source coverage</th></tr>"
                                            f"{body}</table></section>")

    def render_sources(self, L: Links) -> str:
        """Where the archive's records get their sources: Wikipedia alone, anything else, or nothing."""
        r = self.provenance
        wiki, none = r["wikipedia_only"], r["unsourced"]
        other = r["citations"] - wiki
        total = wiki + other + none

        stack = self.stack
        key = lambda k, v, label: f"<span><i class='sw {k}'></i><b>{v:,}</b> {label}</span>"
        out = ["<h1>Sources</h1><div class=sources>",
               f"<section class='panel source-coverage' aria-label='Record source coverage'>{stack(wiki, other, none)}<p class=legend>"
               f"{key('w', wiki, 'Wikipedia only')}{key('o', other, 'other sources')}{key('n', none, 'no source')}"
               f"<span class=meta>{total:,} records</span></p></section>"]
        coll = "".join(f"<tr><td>{e(c['collection'])}</td><td class=num>{c['citations'] + c['unsourced']:,}</td>"
                       f"<td>{stack(c['wikipedia_only'], c['citations'] - c['wikipedia_only'], c['unsourced'])}</td></tr>"
                       for c in sorted(r["collections"], key=lambda c: -(c["citations"] + c["unsourced"])))
        from hydra.wiki import sourcebrowser
        out.append(sourcebrowser.render(self, L))
        out.append("<details class='panel source-breakdown'><summary>Coverage by collection</summary><table class=list>"
                   f"<tr><th>Collection</th><th>Records</th><th>Source coverage</th></tr>{coll}</table></details>")
        return self.frame(L, "Sources", "".join(out) + "</div>")

    def render_settings(self, L: Links) -> str:
        """Settings: what a reader can set for this browser, and what the archive's own wiki.yaml holds."""
        seg = lambda key, attr, default, options, clear="": (
            f"<div class=seg data-key='{key}' data-attr='{attr}' data-default='{default}'{f' data-clear=1' if clear else ''} role=group>"
            + "".join(f"<button type=button data-v='{v}' aria-pressed=false>{e(lab)}</button>" for v, lab in options) + "</div>")
        row = lambda name, note, ctl: (f"<div class=setting><div class=lbl><b>{e(name)}</b><span class=meta>{e(note)}</span></div>{ctl}</div>")
        mine = "".join([
            row("Theme", "Follow your system, or pick one.", seg("hydra-mode", "data-mode", "", [("", "System"), ("light", "Light"), ("dark", "Dark")], clear="1")),
            row("Flags", "How a country's flag is drawn beside its name.",
                seg("hydra-flag", "data-flag", flags.SETTING, [("circle", "Circle"), ("rect", "Rectangle"), ("square", "Square"), ("none", "None")])),
            row("Density", "How much room tables and lists take.",
                seg("hydra-density", "data-density", "comfortable", [("comfortable", "Comfortable"), ("compact", "Compact")])),
            row("Editor view", "Show the notes and tools for people who keep the archive.",
                seg("hydra-review", "data-review", "0", [("0", "Off"), ("1", "On")])),
        ])
        conf = self.conf
        theme = theme_name(conf)
        landing = ", ".join(map(str, conf.get("landing") or ())) or "the shipped order"
        yaml_rows = [
            ("Page layout", conf.get("layout") or "float", "layout", "float: the infobox floats in the page; column: it keeps a column"),
            ("Theme base", theme, "theme.base", "shore, dune, tide, tan or light"),
            ("Flag style", flags.SETTING, "flags", "circle, rect, square or none: the default before a reader chooses"),
            ("Navboxes", "on" if conf.get("navboxes", True) else "off", "navboxes", "the boxes of related entries at the foot of a page"),
            ("Main page sections", landing, "landing", "which sections the main page shows, in order"),
            ("Actions box samples", "on" if conf.get("actions_draft") else "off", "actions_draft", "three sample buttons in the actions box"),
        ]
        table = ("<table class=wikitable><tr><th>Setting</th><th>Value</th><th>Key in wiki.yaml</th><th>What it does</th></tr>"
                 + "".join(f"<tr><td>{e(a)}</td><td>{e(str(b))}</td><td><code>{e(c)}</code></td><td class=meta>{e(d)}</td></tr>" for a, b, c, d in yaml_rows)
                 + "</table>")
        js = ("<script>(function(){function apply(attr,v){var r=document.documentElement;"
              "if(attr==='data-review'?v!=='1':(attr==='data-mode'&&!v))r.removeAttribute(attr);else r.setAttribute(attr,v)}"
              "[].forEach.call(document.querySelectorAll('.seg[data-key]'),function(g){var key=g.dataset.key,attr=g.dataset.attr,def=g.dataset.default;"
              "function cur(){var v=null;try{v=localStorage.getItem(key)}catch(e){}return v===null?def:v}"
              "function mark(){var c=cur();[].forEach.call(g.querySelectorAll('button'),function(b){b.setAttribute('aria-pressed',String(b.dataset.v===c))})}"
              "g.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;var v=b.dataset.v;"
              "try{if(g.dataset.clear&&!v)localStorage.removeItem(key);else localStorage.setItem(key,v)}catch(x){}"
              "apply(attr,v);mark();if(key==='hydra-flag'&&window.hydraFlags)hydraFlags()});mark()})})();</script>")
        body = ("<h1>Settings</h1>"
                "<section class=panel><h2>This browser</h2><p class=note>These apply to you only and take effect at once. "
                "Nothing is written to the archive.</p>" + mine + "</section>"
                "<section class='panel home-block'><h2>This archive</h2><p class=note>What the archive's <code>wiki.yaml</code> sets. "
                "Read-only for now: change them in that file.</p>" + table + "</section>" + js)
        return self.frame(L, "Settings", body)

    def render_groups(self, L: Links) -> str:
        """Every group (houses, parties...) with its size: the page the main page's group portal opens."""
        from hydra.wiki import landing as ld
        label = next((g.get("label") for g in self.groups.values() if g.get("label")), "Group")
        panel = re.sub(r"<h2>.*?</h2>", "", ld.groups(self, L), count=1, flags=re.S)
        return self.frame(L, f"{label}s", f"<h1>{e(label)}s</h1>{panel}")

    def render_current(self, L: Links) -> str:
        """Every post whose last term is open, with its holder: the page "All N" on the main page opens."""
        from hydra.wiki import landing as ld
        return self.frame(L, "Officeholders", f"<h1>Officeholders</h1>{ld.current(self, L, limit=10 ** 6)}")

    def render_changes(self, L: Links) -> str:
        from hydra.wiki import landing as ld
        rows = ld.changes(self, 60)
        items = "".join(f"<tr><td class=meta>{e(d['time'][:10])}</td><td><a href='{L.change(d['sid'])}'>"
                        f"{e(d['message'] or d['headline'])}</a>"
                        + (f"<div class=meta>{e(d['headline'])}</div>" if d["message"] else "")
                        + f"</td><td class=meta>{e(ld._who(d))}</td></tr>" for d in rows)
        items = items or "<tr><td colspan=3 class=meta>No archive changes recorded yet.</td></tr>"
        return self.frame(L, "History", f"<h1>History</h1><table class=wikitable><tr><th>Date</th><th>Change</th>"
                                        f"<th>By</th></tr>{items}</table>")

    @cached_property
    def keyconf(self) -> dict:
        """.hydra/rules/keys.yaml: the namespaces of the keys entries carry."""
        from hydra import keys
        return keys.load(self.root)

    def page_of_key(self, value: str):
        """`wikidata:Q57340` (written any way the namespace compares equal) -> its page's body, or None."""
        from hydra import keys
        k = keys.text(self.keyconf, value)
        return self.by_key.get(k) if k else None

    @cached_property
    def vocab(self) -> dict:
        """.hydra/rules/vocabularies.yaml: what each status and capacity word means."""
        from hydra import vocab
        return vocab.load(self.root)

    def _conf(self) -> dict:
        """`wiki.yaml` in the archive folder, when there is one: what the reader may rearrange.
        Read so far: `chips` (which labels under the title, in order), `badges` (a token's wording; null hides it),
        `sections`, `navboxes`, `layout` (`column`: an entry's side box keeps a column of its own, with the actions box pinned at the bottom of the window while the infobox scrolls under it; both float in the page where the window is narrow), `actions_draft` (show three sample buttons in the actions box, to see it), `landing` (the main page's sections, in order), `panel` (an entry's views and
        their buttons: a list of {label, icon, sections, titles}; see panel.py), `about`, and `theme`:
            theme:
              base: dune                      # shore | dune | tide | tan | light (`--theme` overrides)
              fonts: {heading: "Georgia, serif", body: "system-ui, sans-serif"}
              radius: 12px
              light: {link: "#0f4a44", accent: "#c87a4f"}      # any colour variable of the theme
              dark: {bg: "#1b1614"}"""
        from hydra.wiki import conf as wconf
        return wconf.conf_doc(self.root)

    @staticmethod
    def _coll_names(p) -> list:
        """The collection keys a page (or one of its relation rows) can match: `cits`, `member/cits`."""
        coll = (p or {}).get("collection") or ""
        return [n for x in (coll if isinstance(coll, list) else [coll])
                for n in (x, x.rsplit("/", 1)[-1]) if n]

    def conf_for(self, p) -> dict:
        """The config a page renders with: the archive's, plus its collection's `wiki:` overrides
        in hydra.yaml (`collections: {name: {wiki: {...}}}`)."""
        for n in self._coll_names(p):
            if n in self.coll_conf:
                return self.coll_conf[n]
        return self.conf

    def reg_for(self, p):
        """The compiled lookups (roles/icons/badges) for a page: its collection's, else the base conf's."""
        for n in self._coll_names(p):
            if n in self.regs:
                return self.regs[n]
        return self.reg

    @staticmethod
    def name_key(title: str) -> str:
        return htypes.norm_text(title)

    def _years(self) -> dict:
        """{year: [(kind, person, post)]}: births, deaths, offices taken and left."""
        out = defaultdict(list)
        for b, p in self.pages.items():
            if p["schema"] != self.reg_for(p).roles.PERSON or b not in self.listed:
                continue
            c = views.Ctx(self, None, p)
            for prop, kind in (("birthDate", "births"), ("deathDate", "deaths")):
                y = views.year(c.first(b, prop))
                if y:
                    out[y].append((kind, b, None))
            for r in c.rels(p, c.reg.roles.TENURE, "source"):
                for prop, kind in (("startDate", "took"), ("endDate", "left")):
                    y = views.year(r.get(prop) or (r.get("date") if kind == "took" else None))
                    if y:
                        out[y].append((kind, b, r.get("other") or r.get("name")))
        return {y: list(dict.fromkeys(ev)) for y, ev in out.items()}

    def _facts(self) -> dict:
        """{record id: [message]}: the archive build's `facts.*` findings, keyed by the record they are about."""
        import yaml
        f = self.root / layout.BUILD_YAML
        doc = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.is_file() else {}
        out = defaultdict(list)
        for i in doc.get("issues") or []:
            if str(i.get("code", "")).startswith("facts.") and i.get("where"):
                out[i["where"]].append(i["message"])
        return out

    def banners(self, L: Links, p) -> str:
        """Cleanup banners, as Wikipedia's: no sources; facts that cannot all be true."""
        out = []
        if not any(ci["docs"] or ci["urls"] for ci in p["citations"]):
            out.append("<div class='banner cite m-only'><b>This entry cites no sources.</b> Its records name no document "
                       "and no link; add a source to them so a reader can check it.</div>")
        msgs = list(dict.fromkeys(m for ci in p["citations"] if ci["member"] == U.SELF
                                  for m in self.facts.get(ci["record"], ())))
        if msgs:
            out.append("<div class='banner facts m-only'><b>Facts on this entry cannot all be true.</b> Check them "
                       "against the sources:<ul>" + "".join(f"<li>{e(m)}</li>" for m in msgs) + "</ul></div>")
        return "".join(out)

    def title(self, body, qualified: bool = True):
        """A page's title, with its qualifier when another page shares the title."""
        if isinstance(body, dict):                   # a relation end, or a value
            if body.get("other") or body.get("h"):
                return self.title(body.get("other") or body.get("h"), qualified)
            return body.get("name") or body.get("value") or ""
        p = self.pages.get(body)
        if p:
            return f"{p['title']} ({p['qualifier']})" if qualified and p.get("qualifier") else p["title"]
        return (self.canon.get(body) or {}).get("title") or f"H-{body}"

    def status(self, ref: str) -> tuple[int, str]:
        """-> (http status, body): 200 a page, 301 go to body, 410 a tombstone, 404 none."""
        try:
            body = hid.body(urllib.parse.unquote(ref))
        except ValueError:
            return 404, ref
        if body != ref:
            return 301, body
        if body in self.pages:
            return 200, body
        row = self.canon.get(body)
        if row and row.get("redirect"):
            seen, t = set(), row["redirect"]
            while t in self.canon and self.canon[t].get("redirect") and t not in seen:
                seen.add(t)
                t = self.canon[t]["redirect"]
            return 301, t
        if row and "orphaned" in row["flags"]:
            return 410, body
        return 404, body

    # ---------------------------------------------------------------- rendering

    def brand(self) -> tuple[str, str]:
        """(name, subtitle) the site shows: wiki.yaml `title:` — text, or {text, sub} — else the archive's title."""
        tconf = self.conf.get("title")
        if isinstance(tconf, dict):
            return tconf.get("text") or self.report["title"], tconf.get("sub") or ""
        return tconf or self.report["title"], ""

    def frame(self, L: Links, title: str, inner: str, extra_head: str = "") -> str:
        built = views.long_date(str(self.report.get("built") or "")[:10])
        live = not L.static

        def group(head: str, links) -> str:
            """A heading and its buttons. A link is (title, url, class); `soon(title, what)` is a planned page: grayed out, no link."""
            items = []
            for ln in links:
                if ln[0] == "~":
                    if live:
                        items.append(f"<span class=soon aria-disabled=true title='Planned: {e(ln[2])}'>{ln[1]}<i>Soon</i></span>")
                    continue
                t, u, c = ln
                if u:
                    cur = " aria-current=page" if t == title or (t, title) == ("Timeline", "Years") else ""
                    items.append(f"<a href='{e(u)}'{' class=' + c if c else ''}{cur}>{t}</a>")
            return f"<div class=navgroup>{f'<h2>{head}</h2>' if head else ''}{''.join(items)}</div>" if items else ""
        soon = lambda name, what: ("~", name, what)
        # grouped by what a reader is doing; the grayed entries are planned (docs/plans), not yet built
        nav = (group("", [("Main page", L.home(), ""), ("Browse", live and "/browse", ""), ("Random entry", live and "/random", "")])
               + group("Views", [("Collections", live and "/collections", ""), ("Timeline", self.years and L.years(), ""),
                                 soon("Map", "one country's regions shaded by how many people are linked to each"),
                                 soon("Domains", "who held which kind of post over a period, as portraits")])
               + group("Evidence", [("Sources", live and "/sources", ""),
                                    soon("Documents", "a page for each kept source and everything that cites it"),
                                    soon("Messages", "letters and other correspondence, with their text and the original PDF")])
               + group("Editing", [("Review", live and "/review", "review"), ("Maintenance", live and "/maintenance", ""),
                                   ("History", L.changes(), "")])
               + group("Preferences", [("Settings", live and "/settings", "")]))
        ttext, tsub = self.brand()
        brand = (f"<a class=brand href='{L.home()}'><b>{e(ttext)}</b>"
                 + (f"<i>{e(tsub)}</i>" if tsub else "") + "</a>")
        menu = ("<button class=menu type=button aria-label=Menu aria-expanded=false aria-controls=site "
                "onclick=\"var h=document.getElementById('site');this.setAttribute('aria-expanded',h.classList.toggle('open'))\">"
                "<span></span></button>")
        tools = ("<div class=tools><button class=mode type=button onclick='hydraMode()'>"
                 "<span class=sun>☾ Dark mode</span><span class=moon>☀ Light mode</span></button>"
                 "<button class='mode ed' type=button onclick='hydraReview()' title='Show review notes on every page'>"
                 "Editor view</button></div>")
        return (f"<!DOCTYPE html><html lang=en data-flag='{flags.SETTING}'><head><meta charset=utf-8>"
                f"<meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<title>{e(title)} · {e(self.report['title'])}</title>"
                f"<script>{assets.script('mode.js')}</script>"
                f"<style>{VT}</style><link rel=stylesheet href='{L.asset('wiki.css')}'><link rel=expect href='#end' blocking=render>{extra_head}</head><body>"
                f"<header class=site id=site><div class=bar>{brand}{menu}</div>"
                f"<form class=find action='{L.search()}' role=search><input name=q type=search placeholder='Search the archive' aria-label=Search title='Press / to search'></form>"
                f"<nav aria-label=Site>{nav}</nav>{tools}</header>"
                f"<div class=page><main>{inner}</main>"
                f"<footer id=end>{len(self.listed):,} entries · last built {e(built)} · made with Hydra</footer></div></body></html>")

    STATE = {"c": ("Unreviewed", "a draft id: it can still change when records are added"),
             "p": ("Published", "this address is kept from now on"),
             "d": ("Reviewed", "a person decided which records this entry is made of")}
    FLAG = {"stale": "needs re-review", "conflict": "sources disagree", "redirected": "merged",
            "orphaned": "records gone"}
    FLAG_WHY = {"stale": "a decision about this entity was made on different records than it holds now",
                "conflict": "its sources disagree about a value", "orphaned": "no member holds its records any more"}

    def source_name(self, member: str) -> str:
        """A member as a reader knows it: this archive is its title, not `self`."""
        return self.report["title"] if member == U.SELF else member

    def type_label(self, schema: str, plural: bool = False) -> str:
        return views.type_label(schema, plural)

    def cat_label(self, kind: str, key: str) -> str:
        """A category's name as a reader sees it."""
        if kind == "type":
            return self.type_label(key, plural=True)
        if kind == "member":
            return f"From {self.source_name(key)}"
        if kind == "collection":
            member, _, coll = key.partition("/")
            coll = coll.removeprefix("sources/")
            return f"Collection: {coll}" if len(self.report["members"]) == 1 else f"Collection: {coll} ({self.source_name(member)})"
        if kind == "universe":
            return (self.report["collections"].get(key) or {}).get("title", key)
        return views.CAT_LABEL.get(kind, "{}").format(key)

    def a(self, L: Links, body) -> str:
        """A link to a page. `body` may also be a relation end or a value that names no page:
        a stub is a red link (a name with no record yet), an unresolved name is marked."""
        if isinstance(body, dict):
            if body.get("other") or body.get("h"):
                return self.a(L, body.get("other") or body.get("h"))
            name = body.get("name") or body.get("value") or ""
            if body.get("red"):
                return (f"<a class=new title='no record yet: graduate it with hydra-ctl stubs graduate' "
                        f"href='{L.search()}?q={urllib.parse.quote(name)}'>{e(name)}</a>")
            return f"<span class=unresolved title='names several records, or none: review it'>{e(name)}</span>"
        if body not in self.pages:               # not emitted (a state left out): its name, no link
            return f"<span>{e(self.title(body))}</span>"
        if body not in self.listed:              # context (scope.yaml): named, not linked
            return f"<span title='outside this archive&#39;s scope'>{e(self.title(body))}</span>"
        return f"<a href='{L.page(body)}'>{e(self.title(body))}</a>"

    @staticmethod
    def sup(ns) -> str:
        return "".join(f"<sup><a href='#cite-{n}'>[{n}]</a></sup>" for n in ns)

    def render_page(self, L: Links, body: str) -> str:
        p = self.pages[body]
        out = []
        if p["parents"]:
            out.append("<div class=crumbs>" + "".join(self.a(L, b) for b in p["parents"]) + "</div>")
        qual = f" <span class=qual>({e(p['qualifier'])})</span>" if p.get("qualifier") else ""
        out.append(f"<h1>{e(p['title'])}{qual}</h1>")
        c = views.Ctx(self, L, p)
        out.append(badges.rail(self, p, c))
        out.append(f"<div class='hid m-only'>ID <code title='this entry&#39;s permanent id'>"
                   f"{e(p['h'])}</code>{chips.render(self, L, p, c)}"
                   f" · <a href='{L.talk(body)}'>Review</a></div>")
        if body not in self.listed:              # context (scope.yaml): one quiet line, no banner
            out.append("<p class='meta m-only'>Outside this archive&#39;s scope: named where the entries it concerns mention "
                       "it, and listed nowhere.</p>")
        for f in p["flags"]:
            if f in FLAG_TEXT:
                out.append(f"<div class='banner{'' if f == 'conflict' else ' m-only'}'>{e(FLAG_TEXT[f].format(what=', '.join(p['disagree']) or 'a value'))}"
                           f" <a href='{L.talk(body)}'>Review</a></div>")
        out.append(self.banners(L, p))
        out.append(views.hatnote(p, c))
        column = self.conf_for(p).get("layout") == "column"   # wiki.yaml `layout: column`: the side box keeps a column of its own
        info, widget = views.infobox(p, c), views.action_band(p, c)
        if not column:
            out.append(f"<div class=side>{info}{widget}</div>")
        out.append(views.lead(p, c))
        # the enriched views (family, offices, assets, deals...) go in the panel below the lead, one at a time;
        # references and external links stay below it, always shown (footnotes point there)
        pieces = [(m.__name__, m(p, c)) for m in views.methods_for(p["schema"], self.conf_for(p))]
        pieces += panel.split_relations(self.other_relations(L, p))
        by = self.back_by.get(body) or {}
        if by:
            fl = self.conf.get("field_labels") or {}
            groups = []
            for label, bs in sorted(by.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
                items = "".join(self.conn_item(L, b, self.conn_sub(b, c)) for b in sorted(bs, key=lambda b: (self.conn_year(b, c) or 9999, self.title(b))))
                groups.append(f"<h3>{e(self.mention_head(str(fl.get(label) or label)))} <span class=meta>{len(bs)}</span></h3>"
                              f"<ul class=conns>{items}</ul>")
            pieces.append(("Mentioned in", f"<h2>Mentioned in{views.info('Entries that name this one in a field of their own.')}</h2>{''.join(groups)}"))
        pieces.append(("succession", views.succession(p, c)))
        views_html, rest = panel.render(self, pieces, p)
        slug = lambda h: re.sub(r"<h2>(.*?)</h2>",
                                lambda m: f"<h2 id='{_slug(re.sub(chr(60) + '[^>]*' + chr(62), '', m.group(1)))}'>"
                                          f"{m.group(1)}</h2>", h)
        out.append(slug(views_html))
        out.append(slug(rest + views.references(p, c) + views.links(p, c)))
        if self.conf.get("navboxes", True):
            out.append(visuals.navboxes(p, c))
        # a category every page shares (one archive, one collection) says nothing: left out
        shared = {k for k in ("member", "collection") if len({key for kind, key in self.cats if kind == k}) <= 1}
        cats = [f"<a href='{L.cat(kind, key)}'>{e(self.cat_label(kind, key))}</a>"
                for kind, key in self.page_cats[body] if kind not in shared]
        out.append("<div class=cats>Categories: " + "".join(cats) + "</div>")
        if column:
            out = [f"<div class=entry><aside class=side>{info}</aside><div class=pin>{widget}</div><div class=entry-main>", *out, "</div></div>"]
        return self.frame(L, p["title"], "".join(out), f"<link rel=canonical href='{L.page(body)}'>")

    @staticmethod
    def handled(schema: str, reg=None) -> set:
        """The (edge, side) pairs a schema's display methods already draw."""
        r = reg.roles if reg is not None else roles
        return {r.PERSON: {(r.TENURE, "source"), (r.KIN, "source"), (r.KIN, "target")},
                r.POST: {(r.TENURE, "target")},
                "PublicBody": {("Membership", "target"), ("Membership", "source")},
                "Organization": {("Membership", "target"), ("Membership", "source")}}.get(schema, set())

    def _direction(self) -> tuple[set, set]:
        """(properties marking the upper end of a link, sideways link types), from the
        archive's direction.yaml (else hydra's): the same file the tree is drawn by."""
        if not hasattr(self, "_dir"):
            from hydra import resources, yamlcache
            f = self.root / layout.DIRECTION
            f = f if f.is_file() else resources.TEMPLATE / layout.DIRECTION
            doc = (yamlcache.load(f) or {}) if f.is_file() else {}
            self._dir = (set(doc.get("above") or []), set(doc.get("lateral") or []))
        return self._dir

    @staticmethod
    def mention_head(label: str) -> str:
        """The field that names an entry, as a phrase: "Involved" -> "Involved in", "Organization" -> "Organization of"."""
        low = label.strip().lower()
        return f"{label} in" if low.endswith(("ed", "ing")) else f"{label} of"

    def conn_year(self, b, c):
        p = self.pages.get(b)
        return views.year(c.first(b, "date") or c.first(b, "birthDate")) if p else None

    def conn_sub(self, b, c) -> str:
        """The line under a connected entry: its kind, and its life or year."""
        p = self.pages.get(b)
        if not p:
            return ""
        bits = [views.type_label(p["schema"]), c.life(b) or (str(self.conn_year(b, c) or ""))]
        return " · ".join(e(x) for x in bits if x)

    def conn_item(self, L: Links, ref, sub: str = "", cites: str = "") -> str:
        """One connected entry: its kind's icon, its name as a link, and a quiet line under it."""
        body = ref.get("other") or ref.get("h") if isinstance(ref, dict) else ref
        p = self.pages.get(body)
        ic = icons.for_schema(self.root, p["schema"], 16) if p else ""
        name = self.title(body) if p else ""
        tip = f" title='{e(name, quote=True)}'" if len(name) > 80 else ""      # a long title is clipped: the whole of it on hover
        return (f"<li{tip}><span class=ic>{ic}</span><span class=main>{self.a(L, ref)}{cites}"
                f"{f'<span class=sub>{sub}</span>' if sub else ''}</span></li>")

    def other_relations(self, L: Links, p) -> str:
        """Links no display method takes, laid out by direction.yaml: a sideways link
        (Associate, Representation...) under Relationships; a vertical one as a dated
        table, from below ("Directorships") or from above ("Directors")."""
        reg = self.reg_for(p)
        done = self.handled(p["schema"], reg) | {(reg.roles.OWNERSHIP, "source"), (reg.roles.OWNERSHIP, "target"),
                                            (reg.roles.REPRESENTATION, "source"), (reg.roles.REPRESENTATION, "target")}
        for m in views.methods_for(p["schema"], self.conf_for(p)):   # an edge a defined section draws is not listed again
            done |= (m.covers(reg) if hasattr(m, "covers") else set())
        above, lateral = self._direction()
        groups = defaultdict(list)
        for r in p["relations"]:
            if (r.get("edge"), r.get("side")) in done:
                continue
            if r.get("edge") in lateral:
                groups[("Relationships", "side")].append(r)
            else:
                groups[(r["section"], r["side"])].append(r)
        out = []
        for (sec, side), rs in sorted(groups.items(), key=lambda kv: (kv[0][0] == "Relationships", kv[0])):
            dated = any(r.get("startDate") or r.get("endDate") or r.get("date") for r in rs)
            if side == "side" or not dated:
                out.append(f"<h2>{e(sec)}</h2><ul class=conns>")
                for r in rs:
                    bits = [str(r["verb"]).capitalize()] + [x for x in (r.get("role") if r.get("role") != r.get("verb") else None,) if x]
                    span = "–".join(x for x in (r.get("startDate"), r.get("endDate")) if x) or r.get("date")
                    if span:
                        bits.append(span)
                    out.append(self.conn_item(L, r, " · ".join(e(x) for x in bits), self.sup(r["cites"])))
                out.append("</ul>")
                continue
            named = ((self.conf.get("edge_labels") or {}).get(rs[0].get("edge")) or {}).get(side)
            title = named or (_plural(sec) if side == "source" else _plural(str(rs[0]["verb"]).removesuffix(" of")))
            out.append(f"<h2>{e(title)}</h2><table class=wikitable><tr><th>{e(rs[0]['verb'])}</th><th>Role</th>"
                       f"<th>From</th><th>Until</th></tr>")
            for r in sorted(rs, key=lambda r: (r.get("startDate") or r.get("date") or "9999", self.title(r))):
                out.append(f"<tr><td>{self.a(L, r)}{self.sup(r['cites'])}</td><td>{e(r.get('role') or '')}</td>"
                           f"<td>{e(r.get('startDate') or r.get('date') or '—')}</td><td>{e(r.get('endDate') or '—')}</td></tr>")
            out.append("</table>")
        return "".join(out)

    def render_talk(self, L: Links, body: str) -> str:
        p = self.pages.get(body)
        row = self.canon.get(body) or {}
        state, why = self.STATE.get(row.get("state"), ("", ""))
        problems = ", ".join(self.FLAG.get(f, f) for f in row.get("flags") or []) or "none"
        recs = "".join(f"<li><code>{e(m.split('/', 1)[1] if m.startswith(U.SELF + '/') else m)}</code></li>"
                       for m in row.get("members") or [])
        out = [f"<h1>Review: {e(self.title(body))}</h1>",
               f"<div class=hid><a href='{L.page(body)}'>Back to the entry</a></div>",
               "<table class=wikitable>"
               f"<tr><th>ID</th><td><code>{e(row.get('h', ''))}</code></td></tr>"
               f"<tr><th>Status</th><td>{e(state)} <span class=meta>({e(why)})</span></td></tr>"
               f"<tr><th>Problems</th><td>{e(problems)}</td></tr>"
               f"<tr><th>Made from</th><td><ul class=rel>{recs}</ul></td></tr></table>"]
        if p and p["also"]:
            out.append("<h2>Same name</h2><p>These entries share a name and are kept apart until someone decides. "
                       "If they are one, merge them; if not, mark them as different:</p><ul>")
            for b in p["also"]:
                h2 = self.canon[b]["h"]
                out.append(f"<li>{self.a(L, b)}<br>"
                           f"<code>hydra-ctl universe merge {e(p['h'])} {e(h2)}</code><br>"
                           f"<code>hydra-ctl universe reject {e(p['h'])} {e(h2)}</code></li>")
            out.append("</ul>")
        return self.frame(L, f"Review: {self.title(body)}", "".join(out))

    def render_gone(self, L: Links, body: str) -> str:
        row = self.canon.get(body) or {}
        inner = (f"<h1>{e(row.get('title') or 'Removed entry')}</h1>"
                 f"<div class=banner>This entry was removed: none of its records remain. "
                 f"Its address still answers, so links to it don't break.</div>")
        return self.frame(L, row.get("title") or "Removed entry", inner)

    def render_home(self, L: Links) -> str:
        """The front door: what the archive is, a search box, ways in, people, a featured entry, what's new.
        What the archive holds in full is /browse; what needs doing is /maintenance; changes are /changes
        (all three in the site menu)."""
        return self.frame(L, "Main page", landing.hero(self, L) + landing.render(self, L))

    def render_browse(self, L: Links) -> str:
        """Everything the archive holds: entries by kind, groups, offices, holders, deals, years, collections."""
        r = self.report
        out = ["<h1>Browse</h1>", landing.render(self, L, landing.BROWSE)]
        kinds = {"self": "this archive", "pack": "embedded copy", "path": "linked archive"}
        if len(r["members"]) > 1 or any(m["problem"] for m in r["members"].values()):
            out.append("<h2>Sources of data</h2><table class=list><tr><th>Archive</th><th></th><th>Entries</th><th></th></tr>")
            for name, m in r["members"].items():
                out.append(f"<tr><td><a href='{L.cat('member', name)}'>{e(self.source_name(name))}</a></td>"
                           f"<td>{e(kinds.get(m['kind'], m['kind']))}</td><td>{m['entities']:,}</td>"
                           f"<td>{e(m['problem'])}</td></tr>")
            out.append("</table>")
        faces = sorted((b for b, p in self.pages.items() if views.image(p) and b in self.listed), key=self.title)
        if faces:
            out.append("<section class='panel home-block'><h2>People</h2><div class=gallery>" + "".join(
                f"<a href='{L.page(b)}'><img src='{L.asset(views.image(self.pages[b]))}' alt=''>"
                f"<span>{e(self.title(b))}</span></a>" for b in faces) + "</div></section>")
        held = Counter(kind_key[1] for b, cats in self.page_cats.items() if b in self.listed
                       for kind_key in cats if kind_key[0] == "office")
        if held:
            out.append("<section class='panel home-block'><h2>Offices</h2><p class=tags>" + "".join(
                f"<a href='{L.cat('office', o)}'>{e(o)} <span class=meta>{n}</span></a>" for o, n in held.most_common(30))
                + "</p></section>")
        kinds = sorted(((s, bs) for (k, s), bs in self.cats.items() if k == "type" and s != "Page"),
                       key=lambda kv: (-len(kv[1]), kv[0]))
        if kinds:
            out.append("<h2>By kind</h2><p class=tags>" + "".join(
                f"<a href='{L.cat('type', s)}'>{e(self.type_label(s, plural=True))} "
                f"<span class=meta>{len(bs):,}</span></a>" for s, bs in kinds) + "</p>")
        if r["collections"]:
            out.append("<h2>Collections</h2><p>" + " · ".join(
                f"<a href='{L.cat('universe', k)}'>{e(v['title'])}</a>" for k, v in r["collections"].items()) + "</p>")
        return self.frame(L, "Browse", "".join(out))

    def render_maintenance(self, L: Links) -> str:
        """What needs doing: what the pages lack, entries to look at again, name pairs, notes from the build."""
        r = self.report
        out = ["<h1>Maintenance</h1>", landing.render(self, L, landing.MAINTENANCE)]
        pairs = (r["counts"] or {}).get("proposed") or 0
        if pairs:
            out.append(f"<p>{pairs} pair{'s' if pairs != 1 else ''} of entries share a name"
                       + (" · <a href='/review'>Review</a>" if not L.static else "") + "</p>")
        flagged = [b for b, p in self.pages.items() if p["flags"] and b in self.listed]
        if flagged:
            out.append("<h2>Needs a closer look</h2><ul class=cols>" + "".join(
                f"<li>{self.a(L, b)} <span class=meta>{e(', '.join(self.FLAG.get(f, f) for f in self.pages[b]['flags']))}</span></li>"
                for b in sorted(flagged, key=self.title)[:60]) + "</ul>")
        if r["warnings"]:
            out.append("<h2>Notes from the last build</h2><ul>" + "".join(f"<li>{e(w)}</li>" for w in r["warnings"]) + "</ul>")
        return self.frame(L, "Maintenance", "".join(out))

    EYEBROW = {"collection": "Collection", "universe": "Collection", "member": "Source", "type": "Kind", "office": "Office",
               "births": "Births", "deaths": "Deaths"}

    def render_cat(self, L: Links, kind: str, key: str) -> str:
        """Every entry in a category (a kind, a collection, a house, a year...), by kind, as rows with an icon and a date."""
        bodies = sorted(self.cats.get((kind, key), ()), key=self.title)
        label = self.cat_label(kind, key)
        title = label.removeprefix("Collection: ") if kind == "collection" else label
        eyebrow = self.EYEBROW.get(kind) or next((g.get("label") for g in self.groups.values() if g.get("label")), "") if kind == "group" else self.EYEBROW.get(kind, "")
        c = views.Ctx(self, L, None)
        by_t = defaultdict(list)
        for b in bodies:
            by_t[self.pages[b]["schema"]].append(b)
        kinds = sorted(by_t.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        out = [f"{f'<p class=eyebrow>{e(eyebrow)}</p>' if eyebrow else ''}<h1>{e(title)}</h1>",
               f"<p class=meta>{len(bodies):,} {'entry' if len(bodies) == 1 else 'entries'}</p>"]
        if len(kinds) > 1:                                   # one chip per kind, each jumping to its section
            out.append("<p class=tags>" + "".join(
                f"<a href='#kind-{_slug(s)}'>{icons.for_schema(self.root, s, 14)} {e(self.type_label(s, plural=True))} "
                f"<span class=meta>{len(bs)}</span></a>" for s, bs in kinds) + "</p>")
        sub = lambda b: e(_source_line(self.pages[b]) if self.pages[b]["schema"] == "Article"
                          else c.life(b) or (str(self.conn_year(b, c)) if self.conn_year(b, c) else ""))
        rows = lambda bs: "<ul class=conns>" + "".join(self.conn_item(L, b, sub(b)) for b in bs) + "</ul>"
        for s, bs in kinds:
            if len(kinds) > 1:
                out.append(f"<h2 class=kind id='kind-{_slug(s)}'>{icons.for_schema(self.root, s, 18)}{e(self.type_label(s, plural=True))} "
                           f"<span class=meta>{len(bs)}</span></h2>")
            if len(bs) <= 40:
                out.append(rows(bs))
                continue
            letters = defaultdict(list)                      # a long list: A to Z, with a bar to jump by letter
            for b in bs:
                letters[(self.title(b)[:1] or "#").upper()].append(b)
            anchor = lambda k: f"az-{_slug(s)}-{ord(k)}"
            out.append("<nav class=az aria-label='Jump to letter'>"
                       + "".join(f"<a href='#{anchor(k)}'>{e(k)}</a>" for k in letters) + "</nav>")
            out += [f"<h3 class=letter id={anchor(k)}>{e(k)}</h3>{rows(v)}" for k, v in letters.items()]
        return self.frame(L, title, "".join(out))

    def describe(self, L: Links, b) -> str:
        """One line for a name page: life, parent, the highest office."""
        p = self.pages[b]
        c = views.Ctx(self, L, p)
        bits = [e(c.life(b))] if c.life(b) else []
        if p["schema"] == c.reg.roles.PERSON:
            par = c.parents(p)
            r = par.get("father") or par.get("mother") or par.get("parent")
            if r:
                bits.append(f"{e(c.kin(p, 'son'))} of {self.a(L, r)}")
            terms = views._offices(p, c)
            ranked = sorted((r for r in terms if ((self.pages.get(r.get("other")) or {}).get("rank") or {}).get("depth") is not None),
                            key=lambda r: self.pages[r["other"]]["rank"]["depth"])
            top = (ranked or terms[-1:] or [None])[0]
            if top:
                bits.append(self.a(L, top))
        else:
            org = c.values(p, "organization")
            bits.append(e(self.type_label(p["schema"]).lower()) + (f" in {self.a(L, org[0])}" if org else ""))
        return ", ".join(x for x in bits if x)

    def render_name(self, L: Links, key: str) -> str:
        bodies = self.names.get(key) or []
        if not bodies:
            return self.frame(L, "Not found", "<h1>Not found</h1>")
        name = self.pages[bodies[0]]["title"]
        out = [f"<h1>{e(name)}</h1>", f"<p><b>{e(name)}</b> may refer to:</p>"]
        by_type = defaultdict(list)
        for b in bodies:
            by_type[self.pages[b]["schema"]].append(b)
        life = lambda b: views.year(views.Ctx(self, L, None).first(b, "birthDate")) or 99999
        for s, bs in sorted(by_type.items(), key=lambda kv: kv[0] != self.reg_for(self.pages[kv[1][0]]).roles.PERSON):
            if len(by_type) > 1:
                out.append(f"<h2>{e(self.type_label(s, plural=True))}</h2>")
            out.append("<ul>" + "".join(f"<li>{self.a(L, b)}{', ' + self.describe(L, b) if self.describe(L, b) else ''}</li>"
                                        for b in sorted(bs, key=life)) + "</ul>")
        return self.frame(L, f"{name} (disambiguation)", "".join(out))

    YEAR_KINDS = (("births", "Births"), ("deaths", "Deaths"), ("took", "Took office"), ("left", "Left office"))

    def render_year(self, L: Links, y: int) -> str:
        ev = self.years.get(y)
        if not ev:
            return self.frame(L, "Not found", "<h1>Not found</h1>")
        known = sorted(self.years)
        i = known.index(y)
        nav = (f"<div class=crumbs>{f'<a href={L.year(known[i - 1])!r}>← {known[i - 1]}</a>' if i else ''} "
               f"<a href='{L.years()}'>All years</a> "
               f"{f'<a href={L.year(known[i + 1])!r}>{known[i + 1]} →</a>' if i + 1 < len(known) else ''}</div>")
        out = [nav, f"<h1>{y} in {e(self.report['title'])}</h1>"]
        c = views.Ctx(self, L, None)
        for kind, label in self.YEAR_KINDS:
            rows = [x for x in ev if x[0] == kind]
            if not rows:
                continue
            items = []
            for _, b, post in sorted(rows, key=lambda x: self.title(x[1])):
                if kind in ("births", "deaths"):
                    items.append(f"<li>{self.a(L, b)} <span class=meta>{e(c.life(b))}</span></li>")
                else:
                    where = self.a(L, post) if post in self.pages else e(post or "")
                    items.append(f"<li>{self.a(L, b)}: {where}</li>")
            out.append(f"<h2>{label}</h2><ul{' class=cols' if kind in ('births', 'deaths') else ''}>{''.join(items)}</ul>")
        return self.frame(L, str(y), "".join(out))

    def render_years(self, L: Links) -> str:
        decades = defaultdict(list)
        for y in sorted(self.years):
            decades[y // 10 * 10].append(y)
        top = max((len(v) for v in self.years.values()), default=1)
        def chip(y):                                    # shaded by how much the year holds
            n = len(self.years[y])
            pct = round(8 + 62 * (n / top) ** .6)
            return (f"<a href='{L.year(y)}' title='{n} event{'s' if n != 1 else ''}'{' class=dark' if pct > 52 else ''} "
                    f"style='background:color-mix(in srgb,var(--link) {pct}%,var(--panel))'>{y}</a>")
        out = ["<h1>Years</h1><table class='wikitable years'>"]
        for d, ys in decades.items():
            out.append(f"<tr><th>{d}s</th><td>" + "".join(map(chip, ys)) + "</td></tr>")
        return self.frame(L, "Years", "".join(out) + "</table>")

    def find(self, q: str, limit: int = 100) -> list[tuple[float, str]]:
        keyed = self.page_of_key(q)                 # a key names one entry for certain
        if keyed:
            return [(1.0, keyed)]
        n = htypes.norm_text(q)
        words = n.split()
        hits = []
        for row in self.search_rows:
            names = [htypes.norm_text(x) for x in [row["t"], *row["a"]]]
            if n in names:
                s = 1.0
            elif words and any(all(w in x for w in words) for x in names):
                s = 0.9
            else:
                s = max((difflib.SequenceMatcher(None, n, x).ratio() for x in names), default=0) * 0.8
            if s >= 0.55:
                hits.append((s, row["b"]))
        inside = [h for h in hits if h[1] in self.listed]   # context (scope.yaml) only when nothing in scope matches
        return sorted(inside or hits, key=lambda x: (-x[0], self.title(x[1])))[:limit]

    def render_search(self, L: Links, q: str) -> str:
        """-> (page, None), or (None, where to go): one clear answer goes to its page, a name
        several pages share goes to their name page, as Wikipedia does."""
        hits = self.find(q) if q else []
        if (len(hits) == 1 or (hits and hits[0][0] == 1.0 and (len(hits) < 2 or hits[1][0] < 1.0))) \
                and hits[0][1] in self.listed:   # a context entry is never jumped to: the list says what it is
            return None, L.page(hits[0][1])
        key = self.name_key(q)
        if len(self.names.get(key, ())) > 1:
            return None, L.name(key)
        c = views.Ctx(self, L, None)

        def item(b):                             # a context hit is linked here, and marked
            p, img = self.pages[b], views.image(self.pages[b])
            pic = (f"<img src='{L.asset(img)}' alt='' loading=lazy>" if img
                   else f"<span class=ic>{icons.for_schema(self.root, p['schema'], 18)}</span>")
            link = self.a(L, b) if b in self.listed else f"<a href='{L.page(b)}'>{e(self.title(b))}</a>"
            sub = " · ".join(x for x in (e(self.type_label(p["schema"])), e(c.life(b)),
                                         "" if b in self.listed else "outside this archive&#39;s scope") if x)
            return f"<li>{pic}<span>{link}<span class=meta>{sub}</span></span></li>"
        items = "".join(item(b) for _, b in hits)
        miss = f"No results for “{e(q)}”. <a href='{L.browse()}'>Browse instead</a>"
        count = f"<p class=meta>{len(hits)} result{'s' if len(hits) != 1 else ''}</p>" if hits else ""
        return self.frame(L, f"Search: {q}", f"<h1>Search: {e(q)}</h1>{count}"
                          f"<ul class=hits>{items or f'<li class=meta>{miss}</li>'}</ul>"), None


# -------------------------------------------------------------------- serve / site

def serve(root, port: int = 8080, host: str = "127.0.0.1", theme: str | None = None):
    wiki = Wiki(root)
    L = Links(static=False)
    wiki.page_cache = lru_cache(maxsize=128)(lambda body: wiki.render_page(L, body))
    home = wiki.render_home(L)
    media = Path(root) / layout.UNIVERSE_PARSED
    sheet = css(theme_name(wiki.conf, theme), wiki.conf.get("theme")).encode()   # wiki.yaml `theme:` over the base
    review = (assets.text("review.html")                                          # in the wiki's colours, under its name
              .replace("<!--theme-->", f"<style>{theme_vars(theme_name(wiki.conf, theme), wiki.conf.get('theme'))}</style>")
              .replace("{{archive}}", e(wiki.brand()[0])).replace("<html lang=en>", "<html lang=en class=themed>"))

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body=b"", ctype="text/html; charset=utf-8", location=None, cache=0):
            self.send_response(code)
            if cache:
                self.send_header("Cache-Control", f"public, max-age={cache}")
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            parts = [urllib.parse.unquote(x) for x in url.path.strip("/").split("/") if x]
            html_ = lambda s, code=200: self._send(code, s.encode("utf-8"))
            if not parts:
                return html_(home)
            if parts[0] == "wiki.css":
                return self._send(200, sheet, "text/css")
            if parts[0] == "random" and wiki.listed:
                import random
                return self._send(302, location=L.page(random.choice(sorted(wiki.listed))))
            if parts[0] == "search.json":
                return self._send(200, json.dumps(wiki.search_rows).encode(), "application/json")
            if parts[0] == "search":
                q = (urllib.parse.parse_qs(url.query).get("q") or [""])[0]
                page, go = wiki.render_search(L, q)
                return self._send(302, location=go) if go else html_(page)
            if parts == ["review.json"]:                    # the archive's own open questions, as the page's cards
                from hydra.wiki import reviewqueue
                return self._send(200, json.dumps(reviewqueue.cards(wiki.root)).encode(), "application/json")
            if parts[0] == "review":                        # the decision queue: merges, collisions, fixes
                from hydra.wiki import reviewqueue
                cards = json.dumps(reviewqueue.cards(wiki.root)).replace("</", "<\\/")
                return html_(review.replace("<!--cards-->", f"<script>window.CARDS={cards}</script>"))
            if parts[0] == "flag" and len(parts) == 3 and parts[2].endswith(".svg"):      # /flag/<circle|rect|square>/<code>.svg
                f = flags.file_for(parts[1], parts[2][:-4])
                if not f:
                    return self._send(404)
                return self._send(200, f.read_bytes(), "image/svg+xml", cache=86400)
            if parts[0] in ("sources", "browse", "maintenance", "collections", "groups", "current", "settings") and len(parts) == 1:
                return html_({"sources": wiki.render_sources, "browse": wiki.render_browse,
                              "maintenance": wiki.render_maintenance, "collections": wiki.render_collections,
                              "groups": wiki.render_groups, "current": wiki.render_current,
                              "settings": wiki.render_settings}[parts[0]](L))
            if parts[0] == "changes":                       # /changes, /changes/<id>: what each change did
                return html_(wiki.render_change(L, parts[1]) if len(parts) == 2 else wiki.render_changes(L))
            if parts[0] == "k" and len(parts) >= 3:        # /k/<namespace>/<key>: the entry that key names
                b = wiki.page_of_key(f"{parts[1]}:{'/'.join(parts[2:])}")
                return self._send(302, location=L.page(b)) if b else \
                    html_(wiki.frame(L, "Not found", "<h1>No entry has that key</h1>"), 404)
            if parts[0] == "n" and len(parts) == 2:
                ok = parts[1] in wiki.names and len(wiki.names[parts[1]]) > 1
                return html_(wiki.render_name(L, parts[1]) if ok else wiki.frame(L, "Not found", "<h1>Not found</h1>"),
                             200 if ok else 404)
            if parts[0] == "y" and len(parts) == 2 and parts[1].isdigit() and int(parts[1]) in wiki.years:
                return html_(wiki.render_year(L, int(parts[1])))
            if parts[0] == "years":
                return html_(wiki.render_years(L))
            if parts[0] in ("e", "talk") and len(parts) == 2:
                code, body = wiki.status(parts[1])
                if code == 301:
                    return self._send(301, location=(L.page if parts[0] == "e" else L.talk)(body))
                if code == 404:
                    return html_(wiki.frame(L, "Not found", "<h1>Not found</h1>"), 404)
                if parts[0] == "talk":
                    return html_(wiki.render_talk(L, body))
                return html_(wiki.page_cache(body)) if code == 200 else html_(wiki.render_gone(L, body), 410)
            if parts[0] == "c" and len(parts) == 3 and parts[1] in views.CAT_LABEL:
                return html_(wiki.render_cat(L, parts[1], parts[2]))
            if parts[0] == "media":
                f = (media / "/".join(parts)).resolve()
                if media.resolve() in f.parents and f.is_file():
                    ctype = {".png": "image/png", ".gif": "image/gif", ".svg": "image/svg+xml",
                             ".webp": "image/webp"}.get(f.suffix.lower(), "image/jpeg")
                    return self._send(200, f.read_bytes(), ctype)
            return html_(wiki.frame(L, "Not found", "<h1>Not found</h1>"), 404)

        def log_message(self, fmt, *args):
            pass

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd, wiki


def site(root, out, states=("c", "p", "d"), theme: str | None = None) -> tuple[Path, list[str]]:
    """Write the static site; -> (folder, bodies emitted as pages)."""
    wiki = Wiki(root, states)
    flags.ENABLED = False
    L = Links(static=True)
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    keep = set(wiki.pages)
    write = lambda name, text: (out / name).write_text(text, encoding="utf-8")
    write("wiki.css", css(theme_name(wiki.conf, theme), wiki.conf.get("theme")))
    write("index.html", wiki.render_home(L))
    write("search.html", wiki.frame(L, "Search", "<h1>Search</h1><ul id=hits></ul>", "") .replace(
        "</body>", f"<script>{assets.script('search.js')}</script></body>"))
    (out / "search.json").write_text(json.dumps([r for r in wiki.search_rows if r["b"] in keep],
                                                ensure_ascii=False), encoding="utf-8")
    for b in keep:
        write(L.page(b), wiki.render_page(L, b))
        write(L.talk(b), wiki.render_talk(L, b))
    for b, row in wiki.canon.items():
        if b in keep:
            continue
        code, target = wiki.status(b)
        if code == 301 and target in keep:
            write(L.page(b), f"<!DOCTYPE html><meta charset=utf-8><meta http-equiv=refresh content='0; url={L.page(target)}'>"
                             f"<link rel=canonical href='{L.page(target)}'><a href='{L.page(target)}'>moved</a>")
        elif code == 410:
            write(L.page(b), wiki.render_gone(L, b))
    for (kind, key) in wiki.cats:
        write(L.cat(kind, key), wiki.render_cat(L, kind, key))
    for key, bodies in wiki.names.items():
        if len(bodies) > 1:
            write(L.name(key), wiki.render_name(L, key))
    for y in wiki.years:
        write(L.year(y), wiki.render_year(L, y))
    write(L.years(), wiki.render_years(L))
    src = Path(root) / layout.UNIVERSE_PARSED / "media"
    if src.is_dir():
        shutil.copytree(src, out / "media")
    return out, sorted(keep)
