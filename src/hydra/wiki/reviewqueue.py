"""reviewqueue.py — the open questions of the last build, as the cards the review page shows.

`hydra-ctl review` and hydra-mcp `open_questions` read the same questions (cli/todo.collect); this
turns each into the card the page draws (assets/review.html), so /review.json is the archive's own
queue, not a sample. It reads the last build and writes nothing.

    cards(root) -> [{g, type, ...}]      g: merge | ref | place | stale | contra | broken
"""
from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from hydra import layout, resources
from hydra.cli import todo

SKIP = {"alias", "weakAlias", "sourceUrl", "publisherUrl", "notes", "description", "sources", "keywords"}     # not what tells two entities apart
FIRST = ("name", "birthDate", "deathDate", "nationality", "gender", "position", "wikidataId")


def _claims(root: Path) -> dict[str, dict[str, list[str]]]:
    by: dict = defaultdict(lambda: defaultdict(list))
    for r in resources.read_jsonl(root / layout.CLAIMS_JSONL):
        if r["prop"] not in SKIP and str(r["value"]) not in by[r["entity"]][r["prop"]]:
            by[r["entity"]][r["prop"]].append(str(r["value"]))
    return by


def _side(root_nodes: dict, claims: dict, rid: str, cap) -> dict:
    n = root_nodes.get(rid) or {}
    return {"name": cap or n.get("caption") or rid, "id": rid, "from": rid.split(":", 1)[0] if ":" in rid else "",
            "schema": n.get("schema") or ""}


def _rows(claims: dict, a: str, b: str, conflicts: list) -> list[list]:
    clash = {c["prop"] for c in conflicts or []}
    props = [p for p in dict.fromkeys([*claims.get(a, {}), *claims.get(b, {})]) if p != "name"]     # the names head the columns
    props.sort(key=lambda p: (FIRST.index(p) if p in FIRST else len(FIRST), p))
    out = []
    for p in props[:12]:
        va, vb = "; ".join(claims.get(a, {}).get(p, [])), "; ".join(claims.get(b, {}).get(p, []))
        out.append([p, va, vb, "diff"] if p in clash else [p, va, vb])
    return out


def cards(root) -> list[dict]:
    root = Path(root)
    got = todo.collect(root)
    nodes = resources.declared_nodes(root)
    claims = _claims(root)
    out: list[dict] = []
    for r in got.get("merges") or []:
        a, b = r["a"], r["b"]
        side_a, side_b = _side(nodes, claims, a, r.get("acap")), _side(nodes, claims, b, r.get("bcap"))
        out.append({"g": "merge", "type": "pair", "key": r["id"], "a": side_a, "b": side_b,
                    "rows": _rows(claims, a, b, r.get("conflicts") or [])})
    for r in got.get("references") or []:
        cands = [{"name": c.get("caption") or c["id"], "id": c["id"],
                  "d": c.get("schema") or ""}
                 for c in r.get("candidates") or []]
        out.append({"g": "ref", "type": "ref", "q": f"Which record is “{r['value']}”?",
                    "why": "", "key": r["id"],
                    "in": {"name": r.get("schema") or "Record", "field": r["prop"], "quote": ""}, "cands": cands})
    for r in got.get("placements") or []:
        out.append({"g": "place", "type": "place", "key": r["id"],
                    "q": f"Is “{r.get('subcap')}” under “{r.get('supcap')}”?",
                    "why": ""})
    for kind, g in (("stale", "stale"), ("contradictions", "contra"), ("verdicts", "broken")):
        for r in got.get(kind) or []:
            out.append({"g": g, "type": "orphan", "key": r["id"], "q": str(r.get("message") or r.get("criteria") or r["rel"]),
                        "why": "", "facts": [["Status", html.escape(r.get("status") or "")]]})
    return out
