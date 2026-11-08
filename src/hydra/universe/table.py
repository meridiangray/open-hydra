"""table.py — the H-table (`universe/canon.jsonl`): the universe's promises.

One row per H that something depends on; an H nobody has published or decided
has no row (state c, derived again by every build). A row:

    {"h": "H-d0-7k2m9q4xbz3t",          state only: the flags digit is always 0 here
     "anchor": "self/case:a1",           the record ref the body was derived from
     "members": ["reg/r9", "self/case:a1"],   record refs when it was written (its basis)
     "not": ["q3v8..."],                 bodies it must never merge with
     "redirect": "7k2m...",              merged into another H (written by review)
     "title": "Cy Vale",                 its title when written (a tombstone keeps it)
     "seq": 4, "published": "2026-11-03", "decided": "2026-11-03",
     "by": "...", "source": "..."}       who wrote it, and on what evidence (pins)

Only review and publishing write it, and a state only moves forward (c -> p -> d).
A build reads it and computes flags into `universe/.parsed/`.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from hydra import layout
from hydra.universe import hid

RANK = {"c": 0, "p": 1, "d": 2}


def load(root) -> dict:
    """-> {body: row}, each with its `state` read from `h`."""
    p = Path(root) / layout.CANON
    rows = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                state, _, body = hid.parse(row["h"])
                row["state"] = state or "p"
                rows[body] = row
    return rows


def save(root, rows: dict) -> None:
    out = []
    for body, row in sorted(rows.items(), key=lambda kv: (kv[1].get("seq", 0), kv[0])):
        row = {k: v for k, v in row.items() if k != "state" and v not in (None, [], "")}
        row["h"] = hid.fmt(body, hid.parse(row["h"])[0] or "p", 0)
        out.append(json.dumps(dict(sorted(row.items(), key=lambda kv: kv[0] != "h")), ensure_ascii=False))
    p = Path(root) / layout.CANON
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(l + "\n" for l in out), encoding="utf-8")


def promote(rows: dict, body: str, state: str, *, anchor: str, members, title: str = "",
            today: str | None = None, **extra) -> dict:
    """Write or raise a row to `state` (never lowers one). A new row, or a decision,
    takes `members` as its basis; publishing an existing row leaves its basis alone."""
    today = today or date.today().isoformat()
    row = rows.get(body)
    if row is None:
        row = rows[body] = {"h": hid.fmt(body, state), "state": state, "anchor": anchor,
                            "members": sorted(members),
                            "seq": 1 + max((r.get("seq", 0) for r in rows.values()), default=0)}
    if RANK[state] > RANK[row["state"]]:
        row["state"] = state
        row["h"] = hid.fmt(body, state)
    if state == "d":
        row["members"] = sorted(members)
        row.pop("redirect", None)
    if title:
        row["title"] = title
    row.setdefault("published", today)
    if state == "d":
        row["decided"] = today
    row.update({k: v for k, v in extra.items() if v})
    return row


def follow(rows: dict, body: str) -> str:
    """A body, through any written redirects, to the H it ends at."""
    seen = set()
    while body in rows and rows[body].get("redirect") and body not in seen:
        seen.add(body)
        body = rows[body]["redirect"]
    return body
