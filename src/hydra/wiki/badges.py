"""badges.py — badges worked out from what a page's records say, so no rule has to be written per person.

A person's dated posts and occupations are already in the archive (Occupancy edges to Position pages, and
`position` values). A badge is a rule over those titles:

    now          holds a post with no end date and no death recorded
    king, ruler, crown, governor, minister, ambassador, security      from a post's title (first that fits)
    air, land, navy, guard       service branch, from any title or occupation
    business, finance, energy, media, sport, aviation, academia, arts, philan      industry, the same way

The rules below are the starting set, and name no archive's own bodies or clubs; wiki.yaml `badge_rules:` adds,
changes or removes them, by key (an archive widens a rule's `title` there with its own names):

    badge_rules:
      judge: {label: Judge, group: role, icon: scale, tip: Sat as a judge, title: '\\bjudge\\b'}   # single quotes: YAML reads "\b" as a backspace
      sport: null                      # drop a built-in rule
      governor: {label: Governor}      # change one thing about a built-in rule
    derived_badges: false              # switch them all off

A rule has `title` (a regular expression over a post's title or an occupation, case-insensitive), or `ongoing: true`
(no `title`). `group` is role (first matching role rule only), service or industry. `icon` is a file name under
resources/icons/. `hydra-ctl wiki <archive> badges` lists the rules and how many pages each reaches.
"""
from __future__ import annotations

import re


GROUPS = ("role", "service", "industry")
ROLE_TONE = {"now": "ok", "king": "c", "ruler": "c", "crown": "c"}
GROUP_TONE = {"role": "c", "service": "d", "industry": ""}
KEYS = {"label", "short", "group", "icon", "tip", "title", "ongoing"}

DEFAULTS: dict[str, dict] = {
    "now":        {"label": "In office", "group": "role", "icon": "circle-dot", "ongoing": True,
                   "tip": "Holds a post with no recorded end date"},
    "king":       {"label": "King", "group": "role", "icon": "crown", "title": r"^(?:founder and first )?king\b",
                   "tip": "Monarch / King"},
    "ruler":      {"label": "Ruler", "group": "role", "icon": "castle", "title": r"\bimam\b|\bruler of\b|\bsovereign\b",
                   "tip": "Ruler (Imam / Emir / Sovereign)"},
    "crown":      {"label": "Crown prince", "group": "role", "icon": "star", "title": r"\bcrown prince\b(?!(?:'s)?\s+(?:court|office))",
                   "tip": "Was crown prince or deputy crown prince"},
    "governor":   {"label": "Governor", "group": "role", "icon": "building-2", "title": r"\b(?:governor|viceroy|emir)\b",
                   "tip": "Held a governorship or emirate"},
    "minister":   {"label": "Minister", "group": "role", "icon": "public-body", "title": r"\bminist(?:er|ry)\b",
                   "tip": "Held a ministry"},
    "ambassador": {"label": "Ambassador", "group": "role", "icon": "globe", "title": r"\b(?:ambassador|envoy)\b",
                   "tip": "Served as an ambassador"},
    "security":   {"label": "Military", "group": "role", "icon": "shield",
                   "title": r"intelligence|national guard|commander|forces|defen[cs]e|security|air force|\barmy\b",
                   "tip": "Military or intelligence command"},
    "air":        {"label": "Air force", "group": "service", "icon": "plane",
                   "title": r"air force|air base|aviator|\bpilot\b|air operations", "tip": "Air Force / aviation service"},
    "guard":      {"label": "National Guard", "group": "service", "icon": "shield-check", "title": r"national guard",
                   "tip": "National Guard"},
    "land":       {"label": "Land forces", "group": "service", "icon": "swords", "title": r"land forces|ground forces|\barmy\b|armou?red|infantry",
                   "tip": "Land forces / army service"},
    "navy":       {"label": "Navy", "group": "service", "icon": "anchor", "title": r"\bnavy\b|naval", "tip": "Naval service"},
    "energy":     {"label": "Energy", "group": "industry", "icon": "fuel", "title": r"petroleum|\boil\b|energy|mineral",
                   "tip": "Oil, energy or minerals"},
    "aviation":   {"label": "Aviation", "group": "industry", "icon": "rocket", "title": r"astronaut|space|aviation|aviator|airlines",
                   "tip": "Aviation or spaceflight"},
    "finance":    {"label": "Finance", "group": "industry", "icon": "coins", "title": r"\bbank|financ|investor|investment|holding|stakeholder",
                   "tip": "Finance, banking or investment"},
    "media":      {"label": "Media", "group": "industry", "icon": "newspaper", "title": r"media|broadcast|television|newspaper|marketing group|\bpress\b|publish",
                   "tip": "Media, press or broadcasting"},
    "sport":      {"label": "Sport", "group": "industry", "icon": "trophy",
                   "title": r"football|\bsports?\b|olympic|athlete|equestrian|racer|jumper|esports",
                   "tip": "Sport administration or competition"},
    "academia":   {"label": "Academia", "group": "industry", "icon": "graduation-cap", "title": r"universit|professor|educat|academic|\bschool\b|student union",
                   "tip": "Academia or education"},
    "arts":       {"label": "Arts", "group": "industry", "icon": "palette", "title": r"\bpoet\b|photographer|designer|artist|composer|fashion|jewel|\bwriter\b|novelist",
                   "tip": "Arts, poetry, photography or design"},
    "philan":     {"label": "Philanthropy", "group": "industry", "icon": "heart-handshake",
                   "title": r"philanthrop|charit|foundation|relief|red crescent|welfare society|humanitarian",
                   "tip": "Philanthropy or charitable foundations"},
    "business":   {"label": "Business", "group": "industry", "icon": "chart-no-axes-column", "title": r"businessman|business|chairman|company|entrepreneur|corporat",
                   "tip": "Business / corporate"},
}

RULES: dict[str, dict] = {}
ENABLED = True
_COMPILED: dict[str, re.Pattern] = {}


_ROYAL = r"(?:crown\s+prince|king|queen|prince|princess|emir|sheikh|sultan|president)"
_NAME = r"[A-Z][\w'’-]*"


def _scrub(title: str) -> str:
    """A title without references to other people's offices or namesakes, so "adviser to King Salman",
    "named after Queen Rania" or "Sheikh Zayed University" is not read as that person's reign."""
    t = re.sub(r"\b(?:adviser|advisor|aide|assistant|secretary)\s+(?:to|at|of)\b[^;,]*", " ", title or "", flags=re.I)
    t = re.sub(rf"\b(?:named (?:for|after))\s+{_ROYAL}\b[^;,]*", " ", t, flags=re.I)
    t = re.sub(rf"\b{_ROYAL}\s+{_NAME}(?:\s+(?:bin|ibn|bint|al[-\s])\s*{_NAME})*(?:\s+{_NAME})*", " ", t, flags=re.I)
    return re.sub(r"\s{2,}", " ", t).strip()


def configure(given: dict | None = None, enabled=True) -> None:
    """The rules for the wiki being read: DEFAULTS, then wiki.yaml `badge_rules:` over them (null removes one)."""
    global ENABLED
    if given is not None and not isinstance(given, dict):
        raise ValueError("wiki.yaml badge_rules: must be a mapping of badge key to rule")
    rules = {k: dict(v) for k, v in DEFAULTS.items()}
    for key, spec in (given or {}).items():
        key = str(key)
        if spec is None:
            rules.pop(key, None)
            continue
        if not isinstance(spec, dict):
            raise ValueError(f"wiki.yaml badge_rules: {key}: a mapping with label, group, icon, title ...")
        if bad := set(spec) - KEYS:
            raise ValueError(f"wiki.yaml badge_rules: {key}: unknown key(s) {sorted(bad)}; known: {sorted(KEYS)}")
        if spec.get("group", rules.get(key, {}).get("group", "role")) not in GROUPS:
            raise ValueError(f"wiki.yaml badge_rules: {key}: group is one of {GROUPS}")
        merged = {**rules.get(key, {"group": "role", "label": key.replace("_", " ").capitalize()}), **spec}
        if "title" not in merged and not merged.get("ongoing"):
            raise ValueError(f"wiki.yaml badge_rules: {key}: give `title` (a regular expression) or `ongoing: true`")
        rules[key] = merged
    _COMPILED.clear()
    for key, r in rules.items():
        if r.get("title"):
            try:
                _COMPILED[key] = re.compile(r["title"], re.I)
            except re.error as e:
                raise ValueError(f"wiki.yaml badge_rules: {key}: title is not a valid regular expression: {e}")
    RULES.clear()
    RULES.update(rules)
    ENABLED = enabled is not False


def _texts(wiki, p, c) -> tuple[list[str], list[str], bool]:
    """(post titles, other titles and occupations, holds an open post) for a person."""
    posts, other, ongoing = [], [], False
    dead = bool(c.first(p["body"], "deathDate"))
    for r in c.rels(p, c.reg.roles.TENURE, "source"):
        if r.get("other"):
            posts.append(wiki.title(r, qualified=False))
        if not r.get("endDate") and not dead:
            ongoing = True
    other += [str(v.get("value") or "") for v in c.values(p, "position")]
    return posts, other, ongoing


def derive(wiki, p, c) -> list[str]:
    """The badge keys a page earns, in rule order. Empty for anything but a person.
    Reads the page's own registry (`c.reg.badges`), so a collection's rules apply."""
    return c.reg.badges.derive(wiki, p, c)


def tone(key: str, reg=None) -> str:
    rules = (reg.badges.rules if reg is not None else RULES)
    return ROLE_TONE.get(key) or GROUP_TONE.get(rules[key]["group"], "")


def rail(wiki, p, c) -> str:
    """The badges as a row of pills under the title: an icon, a short label, the rule's tooltip."""
    import html
    from hydra.wiki import icons
    conf = wiki.conf_for(p).get("derived_badges")
    limit = conf.get("max", 8) if isinstance(conf, dict) else 8
    pills = []
    for key in c.reg.badges.derive(wiki, p, c)[:limit]:
        r = c.reg.badges.rules[key]
        pills.append(f"<span class='bd g-{r['group']} k-{html.escape(key)}' title='{html.escape(r.get('tip') or '')}'>"
                     f"{icons.svg(wiki.root, r.get('icon') or '', 16)}{html.escape(r.get('label') or key)}</span>")
    return f"<div class=brail>{''.join(pills)}</div>" if pills else ""


def circles(wiki, p, c) -> str:
    """The badges as icon-only circles in their colour, in their own labelled section of the infobox under the portrait;
    the label is the tooltip."""
    import html
    from hydra.wiki import icons
    conf = wiki.conf_for(p).get("derived_badges")
    limit = conf.get("max", 8) if isinstance(conf, dict) else 8
    dots = []
    for key in c.reg.badges.derive(wiki, p, c)[:limit]:
        r = c.reg.badges.rules[key]
        tip = f"{r.get('label') or key}: {r['tip']}" if r.get("tip") else (r.get("label") or key)
        dots.append(f"<span class='bdc g-{r['group']} k-{html.escape(key)}' title='{html.escape(tip)}'>{icons.svg(wiki.root, r.get('icon') or '', 18)}</span>")
    if not dots:
        return ""
    return (f"<tr><td colspan=2 class=bdcs><div class=bdhead>Badges</div>"
            f"<div class=bdrow>{''.join(dots)}</div></td></tr>")
