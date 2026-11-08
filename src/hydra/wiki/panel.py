"""panel.py — an entry's enriched views, below its lead, one at a time.

Below the lead and the infobox, a row of buttons (Family, Offices, Assets, Deals, Organizations,
Timeline, Connections, As recorded) opens one view at a time; clicking the open one closes it. A
button shows only when its view has something, with a count of what is in it. The choice is
remembered from page to page (localStorage), a link to a section inside a view (`#owners`, the
infobox's "all 6") opens that view, and without JavaScript every view shows, one after another.
References, external links, categories and the foot boxes stay below, always shown.

Which sections go under which button: wiki.yaml `panel:` (a list of {label, icon, sections, titles}),
else TABS; `titles` {section: label} names the button by the first section it holds ("Owners" on an
asset, "Assets" on an owner). A section is named by its method (`family`, `holdings`, `lifebar`...) or, for the relationship
lists the page draws itself, by its heading ("Mentioned in", "Relationships", "Memberships"...).

    split_relations(html) -> [(heading, html)]        the page's other relationships, one per heading
    render(w, pieces, page) -> (panel html, rest)      `pieces`: [(name, html)] in page order
"""
from __future__ import annotations

import html
import re

from hydra.wiki import assets, icons

e = html.escape

TABS = (
    {"label": "Family", "icon": "users", "sections": ["family", "ancestors"]},
    {"label": "Offices", "icon": "briefcase", "sections": ["offices", "holders", "positions", "succession"]},
    {"label": "Assets", "icon": "gem", "sections": ["holdings", "owners", "provenance"],
     "titles": {"owners": "Owners", "provenance": "Owners"}},      # what an entry owns, or (an asset) who owns it
    {"label": "Deals", "icon": "calendar", "sections": ["deals", "parties", "acted_for"]},
    {"label": "Organizations", "icon": "building", "sections": ["@organizations"]},
    {"label": "Timeline", "icon": "calendar", "sections": ["lifebar", "timeline"]},
    {"label": "Connections", "icon": "users", "sections": ["Relationships", "Mentioned in", "@other"]},
    {"label": "As recorded", "icon": "", "sections": ["recorded"]},
)
# relationship lists by heading: the organizational ones; anything else not named goes to "@other"
ORG_WORDS = ("member", "director", "employ", "board", "shareholder", "partner", "affiliat", "subsidiar", "unit")


def split_relations(html_: str) -> list[tuple[str, str]]:
    """The page's own relationship lists (`<h2>Heading</h2>...`), one piece per heading."""
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", html_)
    out = []
    for i in range(1, len(parts) - 1, 2):
        head = re.sub(r"<[^>]+>", "", parts[i]).strip()
        out.append((head, parts[i] + parts[i + 1]))
    return out


def _slot(name: str, tabs) -> int | None:
    """Which tab a piece goes in: its name listed, else an organizational heading, else "@other"."""
    for i, t in enumerate(tabs):
        if name in t["sections"]:
            return i
    if any(w in name.lower() for w in ORG_WORDS):
        return next((i for i, t in enumerate(tabs) if "@organizations" in t["sections"]), None)
    if name[:1].isupper():                         # a heading the page drew: a relationship list
        return next((i for i, t in enumerate(tabs) if "@other" in t["sections"]), None)
    return None


def _count(html_: str) -> int:
    """About how many things a view lists: its table rows, list items, recorded lines, boxes, else links."""
    rows = len(re.findall(r"<tr>\s*<td", html_)) + len(re.findall(r"<li[ >]", html_)) + len(re.findall(r"<dt[ >]", html_))
    return rows or len(re.findall(r"class='?(?:link|anc)\b", html_)) or len(re.findall(r"<a href=", html_))


def render(w, pieces: list[tuple[str, str]], page: dict) -> tuple[str, str]:
    """-> (the panel, what goes below it unchanged). Pieces no tab takes are returned below, in order."""
    tabs = (w.conf or {}).get("panel") or TABS
    tabs = [t for t in tabs if isinstance(t, dict) and t.get("label") and t.get("sections")]
    filled: dict[int, list[str]] = {}
    first: dict[int, str] = {}                    # the first section a tab got: `titles` may name the tab by it
    rest = []
    for name, h in pieces:
        if not h or not h.strip():
            continue
        i = _slot(name, tabs)
        if i is None:
            rest.append(h)
        else:
            filled.setdefault(i, []).append(h)
            first.setdefault(i, name)
    if not filled:
        return "", "".join(rest)
    buttons, panes = [], []
    for i in sorted(filled):
        t = tabs[i]
        label = (t.get("titles") or {}).get(first[i], t["label"])
        pid = "v-" + re.sub(r"[^a-z0-9]+", "-", t["label"].lower()).strip("-")   # stable across entries: remembered
        body = "".join(filled[i])
        n = _count(body)
        ic = icons.svg(w.root, t.get("icon") or "", 15) if t.get("icon") else ""
        buttons.append(f"<button type=button class=tab data-pane='{pid}' aria-controls='{pid}' aria-expanded='false'>"
                       f"{ic}<span>{e(label)}</span>{f'<span class=n>{n}</span>' if n else ''}</button>")
        panes.append(f"<div class=pane id='{pid}' role=region aria-label='{e(label)}'>{body}</div>")
    # the buttons sit right under the lead (beside the infobox, using its space); the open view spreads below it
    return (f"<section class=xpanel aria-label='More about this entry'><div class=tabbar>{''.join(buttons)}</div>"
            f"<div class=panes>{''.join(panes)}</div></section><script>{assets.script('panel.js')}</script>", "".join(rest))
