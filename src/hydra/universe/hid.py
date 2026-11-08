"""hid.py — the H-ID: a universe's canonical id for one entity.

    H-<state><flags>-<body>        H-d4-7k2m9q4xbz3t

body    12 Crockford base32 characters, the identity. Derived, never random:
        hash(universe uid + anchor record ref), so two copies of a universe
        derive the same body for the same cluster. Compare and index by body.
state   c computed (no table row: a build derived it, nothing is promised)
        p published (in the table: something outside points at it)
        d decided  (in the table: a person decided its members)
flags   one hex digit, the sum of what the last build found:
        8 redirected, 4 stale, 2 conflict, 1 orphaned

The table stores the state only; flags are computed by every build and never
written back. A bare `H-<body>` is accepted wherever an H is referenced: the
state and flags are then unknown, the identity is not.
"""
from __future__ import annotations

import hashlib
import re

ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"     # Crockford base32, lowercase: no i, l, o, u
BODY_LEN = 12
STATES = "cpd"
FLAGS = {"redirected": 8, "stale": 4, "conflict": 2, "orphaned": 1}

FULL = re.compile(r"^H-([cpd])([0-9a-f])-([0-9a-hjkmnp-tv-z]{12})$")
BARE = re.compile(r"^H-([0-9a-hjkmnp-tv-z]{12})$")
BODY = re.compile(r"^[0-9a-hjkmnp-tv-z]{12}$")


def b32(text: str, n: int) -> str:
    v = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return "".join(ALPHABET[(v >> (5 * i)) & 31] for i in range(n))


def derive(uid: str, anchor: str) -> str:
    """The body for a cluster anchored at record ref `anchor` in universe `uid`."""
    return b32(f"hydra-h|{uid}|{anchor}", BODY_LEN)


def fmt(body: str, state: str = "c", flags: int = 0) -> str:
    if state not in STATES or not 0 <= flags <= 15 or not BODY.match(body):
        raise ValueError(f"not an H: state={state!r} flags={flags!r} body={body!r}")
    return f"H-{state}{flags:x}-{body}"


def parse(text: str) -> tuple[str | None, int | None, str]:
    """-> (state, flags, body); state and flags are None for a bare `H-<body>` or a body."""
    text = str(text).strip()
    m = FULL.match(text)
    if m:
        return m.group(1), int(m.group(2), 16), m.group(3)
    m = BARE.match(text)
    if m:
        return None, None, m.group(1)
    if BODY.match(text):
        return None, None, text
    raise ValueError(f"not an H: {text!r}")


def body(text: str) -> str:
    return parse(text)[2]


def is_h(text) -> bool:
    try:
        parse(text)
        return True
    except (ValueError, TypeError):
        return False


def split_pin(text: str) -> tuple[str | None, str]:
    """An `upstream` value -> (universe label or None, body). `pollard:H-d4-...` names the
    universe the H belongs to; the label is for people and routing, never for identity."""
    text = str(text).strip()
    label, sep, rest = text.rpartition(":")
    if sep:                          # after a label only `H-...` is an H: `acme:abcdef123456` is a key
        if FULL.match(rest) or BARE.match(rest):
            return label or None, body(rest)
        raise ValueError(f"not an H: {text!r}")
    return None, body(text)


def pin_key(text: str) -> str | None:
    """An `upstream` value as the build compares it: `H-<body>`, or None when it is no H."""
    try:
        return "H-" + split_pin(text)[1]
    except ValueError:
        return None


def flag_names(flags: int) -> list[str]:
    return [name for name, bit in FLAGS.items() if flags & bit]


def flag_value(names) -> int:
    return sum(FLAGS[n] for n in set(names))
