"""Layer 1 — one comparator per FTM property type.

21 FTM property types exist across .hydra/schema/ftm/followthemoney/*.yaml, and
every property on every schema carries exactly one of them. This module is
the only place that knows how to normalize and compare a *value* given its
type — nothing here knows about property names or schema names. Layer 2
(classify.py) decides which category (match/distinct/fold) a property falls
into; this module decides, given two raw values of a known type, whether
they support identity, block it, or say nothing.

Deliberately NOT keyed by property name: `passportNumber`, `iban`,
`taxNumber`, `registrationNumber` all resolve to the same `compare_identifier`
through their shared `type: identifier` — covering every identifier-typed
property on every schema loaded, including ones that don't exist yet.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from datetime import date, timedelta
from enum import Enum
from typing import Callable


class Signal(Enum):
    MATCH = "match"        # supports identity
    CONFLICT = "conflict"  # blocks identity
    NEUTRAL = "neutral"    # says nothing either way


@dataclass(frozen=True)
class Comparison:
    signal: Signal
    how: str  # "exact" | "subset" | "overlap" | "disjoint" | "differs" | "neutral"


NEUTRAL = Comparison(Signal.NEUTRAL, "neutral")

# ---- normalizers ----------------------------------------------------------


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


@lru_cache(maxsize=1 << 18)
def norm_text(v: str) -> str:
    """casefold, strip accents/punctuation, collapse whitespace — for `name`.
    Cached: a build normalizes the same few thousand names millions of times."""
    v = _strip_accents(str(v)).casefold()
    v = _PUNCT.sub(" ", v)
    return _SPACE.sub(" ", v).strip()


def norm_identifier(v: str) -> str:
    """strip everything but alnum, casefold — passportNumber/iban/taxNumber/..."""
    return re.sub(r"[^a-z0-9]", "", str(v).casefold())


def norm_country(v: str) -> str:
    return str(v).strip().casefold()[:2]


def norm_email(v: str) -> str:
    return str(v).strip().casefold()


def norm_phone(v: str) -> str:
    return re.sub(r"[^\d+]", "", str(v))


def norm_url(v: str) -> str:
    v = str(v).strip().casefold()
    v = re.sub(r"^[a-z]+://", "", v)
    v = re.sub(r"^www\.", "", v)
    return v.rstrip("/")


_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def parse_date_range(v: str) -> tuple[date, date] | None:
    """Partial dates cover their whole period: "2008" -> the full year,
    "2008-06" -> the full month. None if unparseable."""
    m = _DATE.match(str(v).strip())
    if not m:
        return None
    y = int(m.group(1))
    if m.group(2) and m.group(3):
        d = date(y, int(m.group(2)), int(m.group(3)))
        return (d, d)
    if m.group(2):
        mo = int(m.group(2))
        start = date(y, mo, 1)
        end_month, end_year = (mo % 12 + 1), (y + 1 if mo == 12 else y)
        end = date(end_year, end_month, 1) - timedelta(days=1)
        return (start, end)
    return (date(y, 1, 1), date(y, 12, 31))


# ---- comparators ------------------------------------------------------------
# Each takes two raw values of a known type and returns a Comparison. Missing
# or unparseable values are always NEUTRAL, never a conflict — absence is not
# evidence of anything (a record missing `birthDate` doesn't block a merge).


def compare_identifier(a: str, b: str) -> Comparison:
    na, nb = norm_identifier(a), norm_identifier(b)
    if not na or not nb:
        return NEUTRAL
    return (Comparison(Signal.MATCH, "exact") if na == nb
            else Comparison(Signal.CONFLICT, "differs"))


compare_iban = compare_identifier
compare_checksum = compare_identifier


def compare_name(a: str, b: str) -> Comparison:
    """Exact normalized match, or word-subset ("Wallace Wright" subset of
    "Wallace Hollis Wright"). Never CONFLICT on its own — a name mismatch
    only blocks a merge via a separate `distinct` field's comparator."""
    na, ta = name_key(a)
    nb, tb = name_key(b)
    if not na or not nb:
        return NEUTRAL
    if na == nb:
        return _EXACT
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if shorter and shorter < longer:
        return _SUBSET
    return NEUTRAL


_EXACT = Comparison(Signal.MATCH, "exact")
_SUBSET = Comparison(Signal.MATCH, "subset")


@lru_cache(maxsize=1 << 18)
def name_key(v: str) -> tuple[str, frozenset]:
    """A name's normalized form and its set of words, computed once per name."""
    n = norm_text(v)
    return n, frozenset(n.split())


def compare_date(a: str, b: str) -> Comparison:
    ra, rb = parse_date_range(a), parse_date_range(b)
    if ra is None or rb is None:
        return NEUTRAL
    if ra == rb:
        return Comparison(Signal.MATCH, "exact")
    overlap = ra[0] <= rb[1] and rb[0] <= ra[1]
    return (Comparison(Signal.MATCH, "overlap") if overlap
            else Comparison(Signal.CONFLICT, "disjoint"))


def compare_country(a: str, b: str) -> Comparison:
    na, nb = norm_country(a), norm_country(b)
    if not na or not nb:
        return NEUTRAL
    return (Comparison(Signal.MATCH, "exact") if na == nb
            else Comparison(Signal.CONFLICT, "differs"))


def _soft_exact(norm: Callable[[str], str]) -> Callable[[str, str], Comparison]:
    """email/phone/url: corroborating, never identity-bearing on their own —
    exact match is a MATCH signal, mismatch is NEUTRAL, never a CONFLICT."""
    def cmp(a: str, b: str) -> Comparison:
        na, nb = norm(a), norm(b)
        if not na or not nb:
            return NEUTRAL
        return Comparison(Signal.MATCH, "exact") if na == nb else NEUTRAL
    return cmp


compare_email = _soft_exact(norm_email)
compare_phone = _soft_exact(norm_phone)
compare_url = _soft_exact(norm_url)

compare_address = compare_name
"""`address` is free text with the same subset relationship as a name
("Alderton" is validly a subset of "Alderton, New Mexico, United
States") — not in classify.py's default `match` type set (no evidence every
address field is identity-bearing), but a real comparator exists for when
one IS explicitly promoted via param.yaml (`Address.full`/`street`/`city`)."""


def compare_number(a: str, b: str) -> Comparison:
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return NEUTRAL
    return Comparison(Signal.MATCH, "exact") if fa == fb else NEUTRAL


def compare_entity(a: str, b: str) -> Comparison:
    """Never called directly. `entity`-typed values are resolved by Layer 3
    (order.py) against the target class's own index before any comparison
    happens — comparing raw entity-reference strings here would repeat the
    Position.distinct: [organization] bug."""
    raise NotImplementedError(
        "entity-typed values are resolved by order.py, never compared directly")


def compare_inert(a: str, b: str) -> Comparison:
    return NEUTRAL


COMPARATORS: dict[str, Callable[[str, str], Comparison]] = {
    "identifier": compare_identifier,
    "iban": compare_iban,
    "checksum": compare_checksum,
    "name": compare_name,
    "date": compare_date,
    "country": compare_country,
    "email": compare_email,
    "phone": compare_phone,
    "url": compare_url,
    "number": compare_number,
    "entity": compare_entity,
    "address": compare_address,
    # inert by type default — listed explicitly so every one of the 21 FTM
    # types has a real entry, never a silent dict.get(..., fallback)
    "string": compare_inert, "text": compare_inert, "topic": compare_inert,
    "boolean": compare_inert, "gender": compare_inert,
    "html": compare_inert, "ip": compare_inert, "json": compare_inert,
    "language": compare_inert, "mimetype": compare_inert,
}

# Which comparator SHAPE a type uses — consulted by index.py so it dispatches
# generically instead of hardcoding per-type checks that silently miss a type
# (found: email/phone/url were already `match=True` by classify.py's own
# default formula, and `address` is promoted by Address.param.yaml, but
# index.py only ever indexed `identifier`/`iban`/`name` — every one of those
# was invisible to candidate generation until this was added).
TOKEN_TYPES = {"name", "address"}           # free text, subset/exact via compare_name-shaped logic
EXACT_TYPES = {"identifier", "iban", "email", "phone", "url"}  # exact-normalized only
HARD_TYPES = {"identifier", "iban", "checksum"}   # an exact match is identity-grade


def strength(ftm_type: str) -> str:
    """How much an exact MATCH on this type is worth to a merge decision:
    `hard` (identifier/iban/checksum — identity-grade), `name` (decisive but
    scope-aware, see scope.py), or `soft` (address/email/phone/url/...:
    corroborating only — many things share an address, a mailbox, a phone —
    so alone it can support a proposal, never an automatic merge). This is
    the signal-strength column of the design, made explicit."""
    if ftm_type in HARD_TYPES:
        return "hard"
    return "name" if ftm_type == "name" else "soft"


NORMALIZERS: dict[str, Callable[[str], str]] = {
    "identifier": norm_identifier, "iban": norm_identifier,
    "email": norm_email, "phone": norm_phone, "url": norm_url,
}


def compare(ftm_type: str, a: str, b: str) -> Comparison:
    """The one entry point every other layer calls. An unrecognized type
    degrades to NEUTRAL rather than raising — a 22nd FTM type introduced
    upstream tomorrow doesn't crash classify.py/merge.py, it's just inert
    until this table is extended."""
    return COMPARATORS.get(ftm_type, compare_inert)(a, b)
