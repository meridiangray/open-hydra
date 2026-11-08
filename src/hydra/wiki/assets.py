"""assets.py — the wiki's stylesheet and scripts, read from `assets/` next to this file.

    wiki.css    the stylesheet; every colour, font and radius is a variable, set by the theme (site.css)
    mode.js     light or dark: inlined in <head>, so a page never flashes the other mode
    panel.js    an entry's one-at-a-time views
    search.js   the static site's search page

They are plain files so another shell (a desktop window, a build step) can take them without
importing Python, and so they can be read and linted as what they are.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent / "assets"


@lru_cache(maxsize=None)
def text(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


def script(name: str) -> str:
    """A script's source without the file's trailing newline, for inlining in a <script> tag."""
    return text(name).strip()
