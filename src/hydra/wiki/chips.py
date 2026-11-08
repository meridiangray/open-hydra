"""chips.py — the small labels under a page's title, from data the build already carries.

Each provider reads one thing the page already has and returns chips; nothing here
is new data. Which providers run, and in what order, is CHIPS (a wiki.yaml `chips:`
list overrides it); how a badge token is worded or hidden is BADGES (a wiki.yaml
`badges:` map overrides it).

    provider    chip                                  from
    state       Unreviewed / Published / Reviewed     the H-id's state
    domain      Person, Public body, Office...        the schema, with its icon
    flags       needs re-review, sources disagree     the H-id's flags
    incumbent   Incumbent: <post>                     the last open term of a post
    badges      hints.yaml badges, flags of countries `badge` / `badges`
    gaps        "n gaps", each named in the tooltip   readiness.gaps
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from hydra.wiki import icons, readiness, views

e = html.escape

CHIPS = ("state", "domain", "flags", "incumbent", "badges", "gaps")      # + "derived": the derived badges, here instead of the rail under the title

# A badge token is an icon's file name. The build gives every node one for its schema (the domain
# chip shows those) and one flag-xx per country; any other token comes from hints.yaml. A label here
# words a hint token; None hides it.
BADGES = {"crown": "Crown", "star-2": "Deputy"}


@dataclass
class Chip:
    kind: str
    text: str
    title: str = ""
    href: str = ""
    tone: str = ""
    icon: str = ""
    maint: bool = False                 # for the people who keep the archive: shown only in the editor view

    def html(self) -> str:
        cls = f"badge {self.kind} {self.tone}{' m-only' if self.maint else ''}".strip()
        inner = self.icon + e(self.text)
        if self.href:
            inner = f"<a href='{e(self.href)}'>{inner}</a>"
        return f"<span class='{cls}' title='{e(self.title)}'>{inner}</span>"


def state(wiki, L, p, c):
    label, why = wiki.STATE[p["state"]]
    return [Chip("state", label, why, tone=p["state"])]


def domain(wiki, L, p, c):
    return [Chip("domain", wiki.type_label(p["schema"]), f"a kind of entry: {p['schema']}",
                 L.cat("type", p["schema"]), icon=icons.for_schema(wiki.root, p["schema"]))]


def flags(wiki, L, p, c):
    return [Chip("flag", wiki.FLAG[f], wiki.FLAG_WHY.get(f, ""), L.talk(p["body"]), "bad", maint=f != "conflict")
            for f in p["flags"] if f in wiki.FLAG]


def incumbent(wiki, L, p, c):
    """A person whose last term in a post is open: the same test the post's own page uses."""
    if p["schema"] != c.reg.roles.PERSON:
        return []
    posts = [r for r in c.rels(p, c.reg.roles.TENURE, "source")
             if r.get("other") and c.incumbent(r) and c.is_latest(p["body"], r)]
    return [Chip("incumbent", f"Incumbent: {wiki.title(r, qualified=False)}",
                 "no end date and no death recorded", L.page(r["other"]), "ok") for r in posts[:2]]


def badges(wiki, L, p, c):
    out, seen = [], set()
    labels = {**BADGES, **(wiki.conf_for(p).get("badges") or {})}
    for token in [p.get("badge"), *(p.get("badges") or [])]:
        if not token or token in seen:
            continue
        seen.add(token)
        if token in icons.SCHEMA_TOKENS:
            continue
        if token.startswith("flag-"):
            code = token[5:]
            from hydra.wiki import flags
            out.append(Chip("country", code.upper(), views.country(code), icon=flags.img(code)))
        elif token in labels:
            if labels[token]:
                out.append(Chip("hint", str(labels[token]), f"hint badge: {token}", icon=icons.svg(wiki.root, token)))
        else:
            out.append(Chip("hint", token.replace("-", " ").capitalize(), "hint badge", icon=icons.svg(wiki.root, token)))
    return out


def derived(wiki, L, p, c):
    """Badges worked out from the page's posts and occupations (badges.py; wiki.yaml `badge_rules:`)."""
    limit = (wiki.conf_for(p).get("derived_badges") or {}).get("max", 8) if isinstance(wiki.conf_for(p).get("derived_badges"), dict) else 8
    out = []
    for key in c.reg.badges.derive(wiki, p, c)[:limit]:
        r = c.reg.badges.rules[key]
        out.append(Chip("hint", r.get("label") or key, r.get("tip") or "", tone=c.reg.badges.tone(key), icon=icons.svg(wiki.root, r.get("icon") or "")))
    return out


def gaps(wiki, L, p, c):
    found = readiness.gaps(p, c.reg)
    if not found:
        return []
    return [Chip("gaps", f"{len(found)} gap{'s' if len(found) > 1 else ''}",
                 "; ".join(w for _, w in found), tone="warn", maint=True)]


PROVIDERS = {"state": state, "domain": domain, "flags": flags, "incumbent": incumbent, "badges": badges, "derived": derived, "gaps": gaps}


def render(wiki, L, p, c) -> str:
    """The page's chips, in the configured order."""
    order = wiki.conf_for(p).get("chips") or CHIPS
    return "".join(ch.html() for name in order if name in PROVIDERS for ch in PROVIDERS[name](wiki, L, p, c))
