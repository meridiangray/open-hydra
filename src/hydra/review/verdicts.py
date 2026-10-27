"""verdicts.py — reading and applying the decisions in `.hydra/review/**/verdicts.yaml` (any depth).

One flat map, `{key: value}` (keys from ids.py):

    merge-… / place-…   confirmed | rejected, or {status, basis}
    ref-…               the record id this reference means (a pin)
    cap-<id>            the name to show for that record (a pin)
    stub-<slug>         the schema a name no record has is graduated as (stubs.py)

`basis` is a fingerprint of the evidence at the time of the decision. A confirm
whose basis no longer matches lapses to `confirmed-stale` (shown again, not
applied); a rejection stays applied and is marked `stale`. Every reader goes
through `status()`, so both value forms work for every kind of row."""
from __future__ import annotations

from pathlib import Path

import yaml

from hydra import layout
from hydra.review import ids

STATUSES = ("confirmed", "rejected")
NONE = "none"           # a `ref-` answer: the text names nothing in this archive
PIN_PREFIXES = ("ref-", "cap-", "stub-")


def status(v) -> str | None:
    """The decision a verdict value records, whichever form it is written in."""
    return v.get("status") if isinstance(v, dict) else v


def basis(v) -> str | None:
    return v.get("basis") if isinstance(v, dict) else None


def status_of(verdicts: dict, key: str) -> str | None:
    return status((verdicts or {}).get(key))


def valid(key, v) -> bool:
    if isinstance(key, str) and key.startswith(PIN_PREFIXES):
        return isinstance(v, str) and bool(v)
    return status(v) in STATUSES


def _yaml(path: Path):
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def files(root) -> list[Path]:
    """Every `verdicts.yaml` under `.hydra/review/`, at any depth; the top one first."""
    dyn = Path(root) / layout.REVIEW_DIR
    top = [dyn / "verdicts.yaml"] if (dyn / "verdicts.yaml").is_file() else []
    return top + sorted(p for p in dyn.rglob("verdicts.yaml") if p.parent != dyn) if dyn.is_dir() else []


def load(root) -> tuple[dict, list[str]]:
    """Union of every verdicts.yaml under `.hydra/review/`. Two files disagreeing
    about one decision: the safe answer (`rejected`) wins; disagreeing pins
    cancel. Disagreements are returned."""
    root = Path(root)
    merged, where, issues = {}, {}, []
    for f in files(root):
        doc = _yaml(f)
        for k, v in (doc.items() if isinstance(doc, dict) else []):
            if not valid(k, v):
                continue
            if k in merged and merged[k] != v:
                issues.append(f"verdict {k}: {where[k]} says {merged[k]}, {f.name} says {v}")
                if k.startswith(PIN_PREFIXES):
                    merged.pop(k)
                else:
                    merged[k] = "rejected"
                continue
            merged.setdefault(k, v)
            where.setdefault(k, f.relative_to(root).as_posix())
    return merged, issues


def pins_from(verdicts: dict | None) -> dict[str, str]:
    """The `ref-` pins: reference key -> chosen record id. `none` ("this text
    names nothing in the archive") is a decision, not a pin."""
    return {k: v for k, v in (verdicts or {}).items()
            if isinstance(k, str) and k.startswith("ref-") and isinstance(v, str) and v != NONE}


def pin_target(pins: dict, record_id: str, prop: str, value: str, exists) -> str | None:
    """The pinned record id for this reference, if it still exists (a pin to a
    vanished record is ignored, never followed)."""
    pid = pins.get(ids.reference_key(record_id, prop, value))
    return pid if pid and exists(pid) else None


def apply(row: dict, verdict) -> None:
    """Set `row["status"]` from a verdict, honouring `basis` when it has one."""
    st = status(verdict)
    if not st:
        return
    vb = basis(verdict)
    drifted = bool(vb and row.get("basis") and vb != row["basis"])
    if st == "confirmed" and drifted:
        row["status"], row["was"] = "confirmed-stale", "confirmed"
    elif st == "rejected" and drifted:
        row["status"], row["stale"] = "rejected", True
    else:
        row["status"] = st
