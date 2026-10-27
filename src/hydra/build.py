"""build.py — the orchestrator: an archive directory in, `.hydra/parsed/*` out.

    hydra-ctl build <archive-dir> [--no-prefix]

Reads `collections/*.json` (+ `manifest.json`), the rules (`defaults/positions.yaml`,
`positions.yaml`, `hints.yaml`, `direction.yaml`), `.hydra/schema/params/` and every
`.hydra/review/**/verdicts.yaml`; prefixes the records (`<prefix>:<local id>`, prefixes
stored back in `collections/manifest.json`); runs the compile once per read
(`self` = rules only, `declared` = rules + hierarchy); and writes
`.hydra/parsed/{generic.json,declared.json,claims.jsonl,identical.jsonl,ledger.jsonl,
parsed.yaml,build.yaml}`. Nothing is carried between builds but the verdicts
(and the previous ledger, only to keep a verdict whose row has vanished,
marked `stale`). No git: it writes files."""
from __future__ import annotations

import gc
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hydra import freshness, ingest as ingest_mod, layout, lint, resources, schema, yamlcache
from hydra.ingest import parse_records
from hydra.review import verdicts as vd
from hydra.shape.reads import build_reads, diff_reads, resolve
from hydra.shape.rules import canonical, compile_rules
from hydra.structure import fold as fold_mod

READS = layout.READS
RECORD_GUIDE = 10_000   # above this, builds slow faster than linearly (common name words)
_PARSED_KEYS = ("positions", "edges", "observed", "unrelated", "issues",
                "carry", "model", "relations", "guide")


def _yaml(path: Path):
    return (yamlcache.load(path) or {}) if path.is_file() else {}


def _dump_json(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def _dump_jsonl(rows) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def merge_ledgers(l1: list, l2: list, prev: list, verdicts: dict) -> list:
    """One ledger for the archive: rows of both reads deduped by id (with the
    reads they occur in); a decided row whose evidence has vanished is kept
    from the previous ledger, marked `stale`."""
    out = {}
    for e in l1 + l2:
        k = e["id"]
        if k in out:
            reads = out[k].setdefault("reads", [])
            for r in e.get("reads") or []:
                if r not in reads:
                    reads.append(r)
            continue
        out[k] = json.loads(json.dumps(e))
    for e in prev:
        st = vd.status_of(verdicts, e["id"])
        if e["id"] not in out and st in vd.STATUSES and e.get("rel") in ("sameAs", "placedUnder"):
            e = {**e, "status": st, "stale": True}
            out[e["id"]] = e
    return sorted(out.values(), key=lambda e: (e["rel"], e["status"], e["id"]))


def _schema_counts(records: list, schema_of: dict) -> dict:
    """{schema: {records, entities}}: records as read, entities after merging;
    most entities first."""
    out: dict = {}
    for r in records:
        out.setdefault(r.get("schema") or "Thing", {"records": 0, "entities": 0})["records"] += 1
    for s in schema_of.values():
        out.setdefault(s, {"records": 0, "entities": 0})["entities"] += 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1]["entities"], -kv[1]["records"], kv[0])))


def _ledger_counts(ledger: list) -> dict:
    names = {"sameAs": "merges", "references": "references", "contradiction": "contradictions",
             "selfEdge": "self_edges"}
    c: dict = {}
    for e in ledger:
        d = c.setdefault(names.get(e["rel"], "placements"), {})
        d[e["status"]] = d.get(e["status"], 0) + 1
    return c


def _observed_titles(records: list[dict]) -> list[str]:
    out = []
    for r in records:
        p = r.get("properties") or {}
        vals = (p.get("role") or []) + (p.get("position") or [])
        if schema.is_a(r["schema"], "Position"):
            vals += p.get("name") or []
        for v in vals:
            if v.strip() and v.strip() not in out:
                out.append(v.strip())
    return sorted(out)


def _drop_duplicate_ids(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the first record with each id (collections in file-name order, records
    in file order) and report every later one: two records cannot share an id,
    and which one a merge would otherwise keep is arbitrary."""
    first: dict[str, dict] = {}
    kept, dropped = [], []
    for r in records:
        if r["id"] in first:
            dropped.append({"id": r["id"], "kept": first[r["id"]].get("_collection", ""),
                            "dropped": r.get("_collection", "")})
            continue
        first[r["id"]] = r
        kept.append(r)
    return kept, dropped


def _title_coverage(records: list[dict], positions: dict) -> dict:
    """Per title source (a `role`, a `position`, a `Position` name): how many
    distinct titles the records carry, how many map to a position, and the
    ones that do not -- what the hierarchy rules still leave uncovered."""
    seen: dict[str, list[str]] = {"role": [], "position": [], "Position.name": []}
    for r in records:
        p = r.get("properties") or {}
        found = {"role": p.get("role") or [], "position": p.get("position") or [],
                 "Position.name": (p.get("name") or []) if schema.is_a(r["schema"], "Position") else []}
        for src, vals in found.items():
            for v in vals:
                v = v.strip()
                if v and v not in seen[src]:
                    seen[src].append(v)
    out = {}
    for src, titles in seen.items():
        miss = sorted(t for t in titles if not canonical(t, positions))
        out[src] = {"titles": len(titles), "matched": len(titles) - len(miss), "unmatched": miss}
    return out


NOTHING = "has no records to build from yet; put records in collections/, then build"


class NothingToBuild(ValueError):
    """The archive has no records yet: collections/ and the source entries are empty."""


def build_archive(root, *, prefix: bool = True, write: bool = True, now: str | None = None,
                  capture: dict | None = None, stubs: dict | None = None) -> dict:
    """Build one archive directory. Returns the build summary (what lands in
    `.hydra/parsed/build.yaml`); with `write=False` nothing is touched. `stubs`
    ({slug: schema}) graduates those names as well as the decided ones: for a
    preview with `write=False` (`tree --stubs`)."""
    # A build makes almost no cyclic garbage, yet every full collection rescans
    # every record. Ten times fewer full collections while building, the
    # caller's setting restored after: ~19% faster on 10k records, same peak memory.
    threshold = gc.get_threshold()
    gc.set_threshold(threshold[0], threshold[1], 100)
    try:
        with yamlcache.frozen():
            return _build_archive(root, prefix=prefix, write=write, now=now, capture=capture, stubs=stubs)
    finally:
        gc.set_threshold(*threshold)


def _build_archive(root, *, prefix: bool, write: bool, now: str | None, capture: dict | None,
                   stubs: dict | None = None) -> dict:
    root = Path(root)
    schema.load(root=root)

    records, collections = [], {}
    cfiles, sfiles = resources.record_files(root)
    for f in cfiles:
        recs = parse_records(f.read_text(encoding="utf-8"))
        for r in recs:
            r["_collection"] = f.stem
        collections[f.stem] = {"records": len(recs), "file": f.name}
        records += recs
    # the source material records cite: read like a collection (prefixed, linked by id),
    # flagged so it is known as a source; documents are evidence, not tree nodes
    for f in sfiles:
        recs = parse_records(f.read_text(encoding="utf-8"))
        name = f"{layout.SOURCE_COLLECTION}{f.stem}"
        for r in recs:
            r["_collection"], r["_source"] = name, True
        collections[name] = {"records": len(recs), "file": f"{layout.SOURCE_ENTRIES}/{f.name}"}
        records += recs
    if not records:
        raise NothingToBuild(f"{root} {NOTHING}")

    manifest_path = root / layout.COLLECTIONS_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    prefix_report = None
    if prefix:
        records, prefix_report = ingest_mod.prefix_records(records, manifest, resources.archive_prefix(root))
        manifest = prefix_report["manifest"]
        for name, info in collections.items():
            info["prefix"] = prefix_report["prefixes"][name]
        if write:
            manifest.setdefault("format", layout.FORMAT_VERSION)
            for name, info in collections.items():
                manifest["collections"].setdefault(name, {}).setdefault("file", info["file"])
            manifest_path.write_text(_dump_json(manifest), encoding="utf-8")

    records, duplicates = _drop_duplicate_ids(records)
    from hydra import stubs as stubs_mod                # names no record has, graduated by a decision
    graduate = {**stubs_mod.decided(vd.load(root)[0]), **(stubs or {})}
    records += stubs_mod.records_for(records, graduate) if graduate else []
    ingest_mod.link_ids(records)                  # FtM id links -> names, the ids kept and followed

    direction_path = root / layout.DIRECTION
    direction = fold_mod.load_direction(direction_path if direction_path.is_file() else None)
    params_dir = root / layout.PARAMS_DIR
    params_dir = params_dir if params_dir.is_dir() else None
    off = resources.defaults_off(root)       # hierarchy defaults switched off read as empty
    rule = lambda name, rel: {} if name in off else _yaml(root / rel)
    generic, declared = rule("generic", layout.DEFAULT_POSITIONS), rule("hierarchy", layout.POSITIONS)
    hints = rule("hints", layout.HINTS)
    verdicts, v_issues = vd.load(root)
    observed = _observed_titles(records)

    rules_generic = compile_rules(generic, None, observed, direction)
    rules_decl = compile_rules(generic, declared, observed, direction)
    shared = resolve(records, verdicts, direction, params_dir)    # rules-independent, once
    kw = dict(overrides=hints, direction=direction, params_dir=params_dir, resolved=shared)
    read1 = build_reads(records, rules_generic, verdicts, read="generic", **kw)
    read2 = build_reads(records, rules_decl, verdicts, read="declared", **kw)

    prev = resources.read_jsonl(root / layout.LEDGER_JSONL) + resources.read_jsonl(root / layout.IDENTICAL_JSONL)
    ledger = merge_ledgers(read1["ledger"], read2["ledger"], prev, verdicts)
    claims = read1["claims"]
    _collection_counts(collections, claims)
    if capture is not None:            # `export`: the build's result in memory, nothing written
        capture.update(resolved=shared, ledger=ledger, reads={ir["read"]: ir for ir in (read1, read2)})
    reads = {ir["read"]: {k: v for k, v in ir.items() if k not in ("ledger", "claims")}
             for ir in (read1, read2)}
    change = diff_reads(read1, read2)
    reads["declared"]["diff"] = change

    meta = _yaml(root / layout.MANIFEST)
    issues = lint.sort(lint.check(root, direction) + lint.build_issues(
        compile_issues=rules_decl["issues"], verdict_disagreements=v_issues, verdicts=verdicts,
        ledger=ledger, nodes=read2["nodes"], records=records, report=read2["report"],
        duplicates=duplicates, prefix_report=prefix_report,
        subject_in_hierarchy=bool((declared or {}).get("subject")),
        record_count=len(records), record_guide=RECORD_GUIDE))
    summary = {
        "format": layout.FORMAT_VERSION, "name": meta.get("name") or root.name,
        **({"subject": meta["subject"]} if isinstance(meta.get("subject"), dict) else {}),
        "built": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": schema.archive_config_hash(root),
        "collections": collections, "records": sum(1 for r in records if not r.get("_stub")),
        **({"stubs": sum(1 for r in records if r.get("_stub"))} if any(r.get("_stub") for r in records) else {}),
        "claims": len(claims),
        "entities": len(shared.ents),
        "schemas": _schema_counts(records, shared.schema_of),
        "reads": {k: {"file": READS[k], "nodes": len(v["nodes"]), "roots": len(v["roots"]),
                      "positioned": sum(1 for n in v["nodes"].values() if n["position"])}
                  for k, v in reads.items()},
        "ledger": _ledger_counts(ledger),
        "declared_changes": {"moved": len(change["moved"]),
                             "newly_positioned": len(change["newly_positioned"])},
        "issues": issues,
        "issue_counts": {lv: sum(1 for i in issues if i["level"] == lv) for lv in lint.LEVELS},
        "title_coverage": {"generic": _title_coverage(records, rules_generic["positions"]),
                           "declared": _title_coverage(records, rules_decl["positions"])},
    }
    if prefix_report:
        summary["prefixes"] = prefix_report["prefixes"]
    if not write:
        return summary

    parsed = {k: rules_decl[k] for k in _PARSED_KEYS if k in rules_decl}
    out = {
        layout.CLAIMS_JSONL: _dump_jsonl(claims),
        layout.IDENTICAL_JSONL: _dump_jsonl([e for e in ledger if e["rel"] == "sameAs"]),
        layout.LEDGER_JSONL: _dump_jsonl([e for e in ledger if e["rel"] != "sameAs"]),
        layout.PARSED_YAML: "# GENERATED by hydra — defaults/positions.yaml ∪ positions.yaml ∪ corpus titles.\n"
                            "# Edit .hydra/rules/positions.yaml or .hydra/rules/defaults/positions.yaml, never this file.\n"
                            + yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True),
        READS["generic"]: _dump_json(reads["generic"]),
        READS["declared"]: _dump_json(reads["declared"]),
        layout.BUILD_YAML: yaml.safe_dump(summary, sort_keys=False, allow_unicode=True),
    }
    for rel, text in out.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    if prefix:                                    # what `build` checks before building again
        yamlcache.remember(root, "last_build", freshness.fingerprint(root))
    return summary


def _collection_counts(collections: dict, claims: list[dict]) -> None:
    """Add to each collection's summary: its claims, its entities another collection
    also supplied (`in_others`), and its `sources` values (`citations`)."""
    per = {name: {"claims": 0, "citations": 0, "entities": set()} for name in collections}
    supplied: dict[str, set] = {}
    for c in claims:
        p = per.get(c["collection"])
        if p is None:
            continue
        p["claims"] += 1
        p["entities"].add(c["entity"])
        supplied.setdefault(c["entity"], set()).add(c["collection"])
        if c["prop"] == "sources":
            p["citations"] += 1
    for name, info in collections.items():
        p = per[name]
        info.update(claims=p["claims"], in_others=sum(1 for e in p["entities"] if len(supplied[e]) > 1),
                    citations=p["citations"])


def report(root, summary: dict, seconds: float | None = None, verb: str = "Built") -> str:
    """The one line a build ends with (it lives with the `build` command, which
    prints it without loading the compiler when the last build stands)."""
    from hydra.cli.build import report as line
    return line(root, summary, seconds, verb)


def main(argv: list[str] | None = None) -> int:
    from hydra.cli import build as build_cli
    return build_cli.main(argv)

if __name__ == "__main__":
    raise SystemExit(main())
