"""captions.py — the one name shown for a record, everywhere it is shown.

The tree, the merge rows and the reference pick-lists all label a record the
same way: a pinned name (verdict `cap-<id>` naming one of the record's own
values) wins, else the fullest name (most words, then most characters, then
first seen), else its `title`, a page index, or its id."""
from __future__ import annotations

from hydra.identity.types import norm_text
from hydra.review import ids


def caption(rec: dict, verdicts: dict | None = None) -> str:
    props = rec.get("properties") or {}
    names = props.get("name") or []
    pin = (verdicts or {}).get(ids.caption_key(rec["id"]))
    if isinstance(pin, str) and pin in names:
        return pin
    if names:
        return max(names, key=lambda n: (len(norm_text(n).split()), len(n), -names.index(n)))
    return (props.get("title") or
            (["p." + props["index"][0]] if props.get("index") else [rec["id"]]))[0]
