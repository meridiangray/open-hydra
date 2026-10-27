"""Merge evaluation on a small labelled corpus (tests/corpus2/): precision and
recall of hydra's automatic merges, of everything it puts to a person, and of an
exact-name baseline. Run directly for a table:

    python3 tests/merge_eval.py
"""
from __future__ import annotations

import itertools
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from _template import copy_template  # noqa: E402
from hydra import build  # noqa: E402

CORPUS = HERE / "corpus2"


def truth_pairs() -> set[frozenset]:
    doc = yaml.safe_load((CORPUS / "truth.yaml").read_text(encoding="utf-8"))
    return {frozenset(p) for cluster in doc["same"] for p in itertools.combinations(cluster, 2)}


def build_corpus(dest: Path) -> Path:
    root = copy_template(dest)
    for f in (CORPUS / "collections").glob("*.json"):
        shutil.copy(f, root / "collections" / f.name)
    build.build_archive(root, now="2026-01-01T00:00:00+00:00")
    return root


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def hydra_pairs(root: Path) -> tuple[set[frozenset], set[frozenset]]:
    """(merged, proposed): pairs merged into one node, and pairs put to a person."""
    nodes = json.loads((root / ".hydra" / "parsed" / "generic.json").read_text(encoding="utf-8"))["nodes"]
    merged = {frozenset(p) for n in nodes.values()
              for p in itertools.combinations(n.get("referents") or [], 2)}
    proposed = {frozenset((e["a"], e["b"])) for e in _jsonl(root / ".hydra" / "parsed" / "identical.jsonl")
                if e["status"] in ("proposed", "conflict", "confirmed-stale")}
    return merged, proposed - merged


def baseline_pairs(root: Path) -> set[frozenset]:
    """Exact-name baseline: two records of the same schema sharing a name,
    compared case-insensitively. No accents, aliases or identifiers."""
    recs = []
    for f in sorted((root / "collections").glob("*.json")):
        if f.name == "manifest.json":
            continue
        prefix = json.loads((root / "collections" / "manifest.json").read_text())["collections"][f.stem]["prefix"]
        for r in json.loads(f.read_text(encoding="utf-8")):
            names = {n.casefold().strip() for n in r.get("properties", {}).get("name", [])}
            recs.append((f"{prefix}:{r['id']}", r["schema"], names))
    return {frozenset((a, b)) for (a, sa, na), (b, sb, nb) in itertools.combinations(recs, 2)
            if sa == sb and na & nb}


def score(found: set, truth: set) -> dict:
    tp = len(found & truth)
    return {"found": len(found), "correct": tp,
            "precision": tp / len(found) if found else 1.0,
            "recall": tp / len(truth) if truth else 1.0}


def evaluate(work: Path) -> dict:
    root = build_corpus(work / "corpus2")
    truth = truth_pairs()
    merged, proposed = hydra_pairs(root)
    return {"truth": len(truth), "root": root,
            "hydra_auto": score(merged, truth),
            "hydra_surfaced": score(merged | proposed, truth),
            "baseline": score(baseline_pairs(root), truth),
            "merged": merged, "proposed": proposed, "baseline_pairs": baseline_pairs(root)}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        r = evaluate(Path(d))
        print(f"{r['truth']} true pairs")
        print(f"{'':16}{'found':>7}{'correct':>9}{'precision':>11}{'recall':>8}")
        for k in ("hydra_auto", "hydra_surfaced", "baseline"):
            s = r[k]
            print(f"{k:16}{s['found']:>7}{s['correct']:>9}{s['precision']:>11.2f}{s['recall']:>8.2f}")
        for label, pairs in (("merged", r["merged"]), ("proposed", r["proposed"]),
                             ("baseline", r["baseline_pairs"])):
            print(f"\n{label}:")
            for p in sorted(sorted(x) for x in pairs):
                print("  ", " = ".join(p), "" if frozenset(p) in truth_pairs() else "   (not a true pair)")
