"""Partial FTM dates -> comparable ranges.

FTM dates may be a year (`2008`), a month (`2008-10`) or a day. A partial
date means the whole period, so "ended 2008" ends on 2008-12-31 and "started
2009-03" starts on 2009-03-01. Used to rank placements (active before ended,
most recent start) and to tell overlapping alternatives from career history."""
from __future__ import annotations

import re

_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


def bounds(value):
    """One date string -> (first day, last day) as ISO strings, or None."""
    m = _RE.match(str(value or "").strip())
    if not m:
        return None
    y, mo, d = m.groups()
    if d:
        return f"{y}-{mo}-{d}", f"{y}-{mo}-{d}"
    if mo:
        return f"{y}-{mo}-01", f"{y}-{mo}-31"
    return f"{y}-01-01", f"{y}-12-31"


def span(start=(), end=()):
    """startDate / endDate value lists -> (lo, hi). Missing bound -> None
    (open) — a record with a startDate but no endDate is still ongoing."""
    s = [b for b in map(bounds, start or ()) if b]
    e = [b for b in map(bounds, end or ()) if b]
    return (min(b[0] for b in s) if s else None,
            max(b[1] for b in e) if e else None)


def earliest(values=()):
    """The value whose period starts first (the one `span()` takes its low
    bound from), whatever order the values arrive in; undated values only
    when nothing parses. None when empty."""
    keyed = [((b is None, b[0] if b else "", v), v) for v in values or () if v
             for b in (bounds(v),)]
    return min(keyed)[1] if keyed else None


def latest(values=()):
    """The value whose period ends last (`span()`'s high bound). None when empty."""
    keyed = [((b is not None, b[1] if b else "", v), v) for v in values or () if v
             for b in (bounds(v),)]
    return max(keyed)[1] if keyed else None


def overlaps(a, b) -> bool:
    """True unless both spans are known and disjoint. Unknown means "can't
    tell", which counts as overlapping so that undated evidence stays
    ambiguous rather than silently sequential."""
    (alo, ahi), (blo, bhi) = a, b
    return ((alo is None or bhi is None or alo <= bhi)
            and (blo is None or ahi is None or blo <= ahi))


def key_start(sp) -> str:
    """Sort key: later start = more recent. Unknown start sorts first
    (empty string sorts before any real date)."""
    return sp[0] or ""
