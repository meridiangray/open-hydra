"""Partial FTM dates -> comparable ranges.

FTM dates may be a year (`2008`), a month (`2008-10`) or a day. A partial
date means the whole period, so "ended 2008" ends on 2008-12-31 and "started
2009-03" starts on 2009-03-01. Used to rank placements (active before ended,
most recent start) and to tell overlapping alternatives from career history."""
from __future__ import annotations

import calendar
import re
from datetime import date as _date

_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
_YEAR = re.compile(r"\b(\d{4})\b")


def year(value) -> int | None:
    """First 4-digit year in `value`, or None."""
    m = _YEAR.search(str(value or ""))
    return int(m.group(1)) if m else None


def bounds(value):
    """One date string -> (first day, last day) as ISO strings, or None."""
    m = _RE.match(str(value or "").strip())
    if not m:
        return None
    y, mo, d = m.groups()
    if d:
        return f"{y}-{mo}-{d}", f"{y}-{mo}-{d}"
    if mo:
        return f"{y}-{mo}-01", f"{y}-{mo}-{calendar.monthrange(int(y), int(mo))[1]:02d}"
    return f"{y}-01-01", f"{y}-12-31"


def date_range(value) -> tuple[_date, _date] | None:
    """One date -> (first day, last day) as `date`s, or None. An approximate value
    ("c. 1748", "1950s") gives the period of the date it holds."""
    d, _kind = exact(str(value or "").strip())
    b = bounds(d) if d else None
    return (_date.fromisoformat(b[0]), _date.fromisoformat(b[1])) if b else None


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


# ---- approximate dates ------------------------------------------------------------
# FtM dates are exact prefixes, so a source's "c. 1748" keeps its date (`1748`) in the
# property and its qualifier in the record's `_meta: {approx: {birthDate: circa}}`, which
# hydra keeps through the build: an FtM export stays valid, and a page can say "c. 1748".

#
# The qualifiers are ISO 8601-2's (EDTF, the Extended Date/Time Format), so a date written in
# EDTF is read, and `edtf()` writes one back for tools that read it:
#     circa      c. 1748       1748~          (EDTF approximate; `1748%` read as circa too)
#     uncertain  1748?         1748?
#     decade     1950s         195X
#     before     before 1800   [..1800]       (`../1800` read too)
#     after      after 1900    [1900..]       (`1900/..` read too)

APPROX = {"circa": "c.", "before": "before", "after": "after", "decade": "s", "uncertain": "?"}
_D = r"(\d{4}(?:-\d{2}(?:-\d{2})?)?)"
_APPROX = [
    (re.compile(rf"^(?:c\.?|ca\.?|circa|about|around|~)\s*{_D}$", re.I), "circa"),
    (re.compile(rf"^{_D}[~%]$"), "circa"),
    (re.compile(rf"^(?:before|bef\.?|<)\s*{_D}$", re.I), "before"),
    (re.compile(rf"^(?:\[\.\.{_D}\]|\.\./{_D})$"), "before"),
    (re.compile(rf"^(?:after|aft\.?|>)\s*{_D}$", re.I), "after"),
    (re.compile(rf"^(?:\[{_D}\.\.\]|{_D}/\.\.)$"), "after"),
    (re.compile(r"^(\d{3})0s$"), "decade"),
    (re.compile(r"^(\d{3})X$"), "decade"),
    (re.compile(rf"^{_D}\s*\?$"), "uncertain"),
]


def approx(value) -> tuple[str | None, str | None]:
    """'c. 1748' -> ('1748', 'circa'); '1950s' -> ('195', 'decade'); '1748' -> ('1748', None);
    anything else -> (None, None). A decade keeps three digits: FtM reads `195` as no date,
    so a decade is written as its first year with the qualifier (see `exact`)."""
    v = str(value or "").strip()
    if bounds(v) is not None and _RE.fullmatch(v):
        return v, None
    for rx, kind in _APPROX:
        m = rx.match(v)
        if m:
            return next(g for g in m.groups() if g), kind
    return None, None


def exact(value) -> tuple[str | None, str | None]:
    """An approximate date as the date FtM stores and its qualifier: '1950s' -> ('1950', 'decade')."""
    d, kind = approx(value)
    if kind == "decade":
        return d + "0", kind
    return d, kind


def show(value: str, kind: str | None) -> str:
    """A stored date and its qualifier, as a page writes it: ('1748', 'circa') -> 'c. 1748'."""
    if kind == "circa":
        return f"c. {value}"
    if kind in ("before", "after"):
        return f"{kind} {value}"
    if kind == "decade":
        return f"{value}s"
    if kind == "uncertain":
        return f"{value}?"
    return value


def edtf(value: str, kind: str | None) -> str:
    """A stored date and its qualifier in EDTF (ISO 8601-2): ('1748', 'circa') -> '1748~',
    ('1950', 'decade') -> '195X', ('1800', 'before') -> '[..1800]'. An exact date is itself."""
    v = str(value or "")
    if kind == "circa":
        return f"{v}~"
    if kind == "uncertain":
        return f"{v}?"
    if kind == "decade":
        return f"{v[:3]}X"
    if kind == "before":
        return f"[..{v}]"
    if kind == "after":
        return f"[{v}..]"
    return v
