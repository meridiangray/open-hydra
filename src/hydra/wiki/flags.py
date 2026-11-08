"""flags.py — a country's flag, drawn from two npm packages fetched at build time (flagdata.py).

    circle   circle-flags   a circle, drawn for it              assets/flags/circle/<code>.svg
    rect     flag-icons     the flag, 4 by 3                    assets/flags/rect/<code>.svg
    square   flag-icons     the flag, 1 by 1                    assets/flags/square/<code>.svg

Both are MIT-licensed (see NOTICE.md). The SVGs are not in the repo: the wheel build downloads them (setup.py)
and a checkout gets them with `python -m hydra.wiki.flagdata`; `$HYDRA_FLAGS_DIR` overrides the folder entirely
(same `<style>/<code>.svg` layout). The code comes from `standards.country_code`, so a name, a demonym or an ISO
code all work; a value that is no country, or a country with no file, gets no flag. Which style a page shows is
wiki.yaml `flags:` (circle, rect, square, none) and, per reader, Settings; the markup is one
`<img class=flag data-cc=..>` and `mode.js` swaps its `src` for the reader's style.

    img(value) -> "<img ...>" or ""        file_for(style, code) -> Path | None       configure(value)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from hydra import standards
from hydra.wiki import flagdata

STYLES = ("circle", "rect", "square")
ENABLED = True              # off while the static site is written: it has no /flag/ route to serve them
DEFAULT = "circle"          # what pages draw before a reader's own choice is applied
SETTING = "circle"          # wiki.yaml `flags:` as given (circle, rect, square or none): the page's data-flag


def configure(value) -> None:
    global DEFAULT, SETTING
    SETTING = value if value in STYLES or value == "none" else "circle"
    DEFAULT = SETTING if SETTING in STYLES else "circle"


def _roots() -> list[Path]:
    found = [Path(os.environ["HYDRA_FLAGS_DIR"])] if os.environ.get("HYDRA_FLAGS_DIR") else []
    return [p for p in found + [flagdata.DIR] if p.is_dir()]


def code(value) -> str:
    cc = standards.country_code(str(value or ""))
    return cc if re.fullmatch(r"[a-z]{2}", cc) and cc != "xx" else ""       # circle-flags' "xx" is an unknown-country placeholder


def file_for(style: str, cc: str) -> Path | None:
    if style not in STYLES or not re.fullmatch(r"[a-z]{2}", cc or "") or cc == "xx":
        return None
    for root in _roots():
        f = root / style / f"{cc}.svg"
        if f.is_file():
            return f
    return None


def img(value) -> str:
    """The flag for a country (a code, a name, a demonym), or "" when there is none to draw."""
    cc = code(value)
    if not ENABLED or not cc or not file_for(DEFAULT, cc):
        return ""
    return f"<img class=flag data-cc={cc} src='/flag/{DEFAULT}/{cc}.svg' alt='' loading=lazy>"
