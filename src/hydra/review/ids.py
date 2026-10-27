"""ids.py — every id the compiler derives, in one place.

Record ids are never generated: a merge keeps one of its records' own ids, and
`survivor()` follows the chain from a merged-away id to the one that kept it.
Ledger and verdict keys are derived from record ids (and, for a reference, the
property and value), so the build and anything that writes `verdicts.yaml` agree.

    merge-<16 hex>    a sameAs row: the two record ids
    ref-<16 hex>      a references row: record id, property, value
    place-<16 hex>    a placement row: child id, parent id
    cap-<record id>   a caption pin
    contra-<merge-…>  a rejected sameAs merged anyway through other links
    grp-<12 hex>      a group of sameAs rows answering one question
    cyc-<12 hex>      a cycle among placements: its sorted members
"""
from __future__ import annotations

import hashlib



def survivor(survivors: dict[str, str], rid: str) -> str:
    """The id `rid` was merged into, following the chain to its end."""
    while survivors.get(rid, rid) != rid:
        rid = survivors[rid]
    return rid


def _h(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def merge_key(a: str, b: str) -> str:
    return "merge-" + _h("|".join(sorted((a, b))))


def reference_key(record_id: str, prop: str, value: str) -> str:
    return "ref-" + _h("\x1f".join((record_id, prop, value)))


def place_key(child: str, parent: str) -> str:
    """A placement row: the child's and the parent's (survivor) ids."""
    return "place-" + _h("\x1f".join((child, parent)))


def caption_key(record_id: str) -> str:
    return "cap-" + record_id


def contradiction_key(merge_id: str) -> str:
    return "contra-" + merge_id


def group_key(focus: str) -> str:
    """A group of sameAs rows sharing one record (the focus)."""
    return "grp-" + _h(focus, 12)


def similar_group_key(record_id: str, candidate: str, match: str) -> str:
    """The rows answering one `Similar` record's (candidate, match) question."""
    return "grp-" + _h(f"{record_id}|{candidate}|{match}", 12)


def cycle_key(members) -> str:
    return "cyc-" + _h("|".join(members), 12)
