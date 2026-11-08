"""icons.py — the small drawings beside a label: one per kind of entry (its domain) and per hint badge.

A badge token is an icon's file name under `.hydra/resources/icons/`: the archive's own
folder first, then the icons hydra ships. The files are inlined, so they take the text's colour.
"""
from __future__ import annotations

import re
from pathlib import Path

from hydra import layout, resources

# the domain of an entry: the icon of its schema (the build gives nodes the same four as `badges`)
SCHEMA_ICON = {"Person": "user", "Organization": "users", "PublicBody": "landmark", "Company": "building",
               "LegalEntity": "building", "Position": "briefcase", "Asset": "gem", "RealEstate": "house",
               "Vessel": "ship", "Airplane": "plane", "Event": "calendar", "Article": "newspaper"}
SCHEMA_TOKENS = {"user", "users", "landmark", "building"}      # the build's per-schema badges: the domain chip says them
FILE = {"landmark": "public-body"}                              # a token whose file has another name
_cache: dict = {}


def svg(root, token: str, size: int = 14) -> str:
    """The icon inline, or "" when no file has that name."""
    name = FILE.get(token, token)
    if not re.fullmatch(r"[a-z0-9-]+", name or ""):
        return ""
    key = (str(root), name, size)
    if key not in _cache:
        _cache[key] = ""
        for base in (Path(root) / layout.RESOURCES_DIR, resources.TEMPLATE / layout.RESOURCES_DIR):
            f = base / "icons" / f"{name}.svg"
            if f.is_file():
                text = re.sub(r"<!--.*?-->", "", f.read_text(encoding="utf-8"), flags=re.S)
                text = re.sub(r'class="[^"]*"', 'class="ico" aria-hidden="true"', text, count=1)
                text = text.replace('width="24"', f'width="{size}"', 1).replace('height="24"', f'height="{size}"', 1)
                _cache[key] = re.sub(r"\s*\n\s*", " ", text).strip()
                break
    return _cache[key]


OVERRIDE: dict[str, str] = {}               # wiki.yaml `icons:`, set when a wiki loads


def configure(given: dict | None) -> None:
    """wiki.yaml `icons: {Schema: icon-name}` over SCHEMA_ICON. An icon name is a file name under resources/icons/."""
    if given is not None and not isinstance(given, dict):
        raise ValueError("wiki.yaml icons: must be a mapping of schema name to icon name")
    bad = [f"{k}: {v!r}" for k, v in (given or {}).items() if not re.fullmatch(r"[a-z0-9-]+", str(v))]
    if bad:
        raise ValueError(f"wiki.yaml icons: an icon is a file name like 'ship' (letters, digits, -): {', '.join(bad)}")
    OVERRIDE.clear()
    OVERRIDE.update({str(k): str(v) for k, v in (given or {}).items()})


def token(schema: str) -> str:
    """The icon name for a page type: wiki.yaml's, else the built-in one, on the type or its nearest ancestor
    (Vessel -> Vehicle -> Asset)."""
    from hydra import schema as hschema
    chain = hschema.ancestors(schema) or (schema,)
    return next((OVERRIDE[n] for n in chain if n in OVERRIDE), None) or next((SCHEMA_ICON[n] for n in chain if n in SCHEMA_ICON), "")


def for_schema(root, schema: str, size: int = 14) -> str:
    return svg(root, token(schema), size)
