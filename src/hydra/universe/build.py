"""build.py — the universe build: members + H-table in, `universe/.parsed/` out.

    members (read only, compiled by the archive build) ─┐
    universe/canon.jsonl  (read only)                   ├─► .parsed/canon.jsonl   every H, with its flags
    universe/review, collections                        ┘   .parsed/report.json   members, counts, warnings
                                                            .parsed/pages.jsonl   one page per live H  (pages=True)
                                                            .parsed/search.json   title, aliases, schema
                                                            .parsed/media/        the images pages show

`hydra-ctl build` runs the identity half for a universe of one (`self` alone),
reusing the archive it has just compiled, so every build of such an archive
gives its entities Hs. `hydra-ctl universe build` runs it all, every member.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from hydra import keys, layout
from hydra import scope as scope_mod
from hydra.universe import identity, layer, pages as pages_mod, table


def build(root, *, capture: dict | None = None, pages: bool = True, now: str | None = None) -> dict:
    root = Path(root)
    doc = layer.read_manifest(root)
    uid = str(doc["uid"])
    members = layer.load_members(root, doc, capture)
    rows = table.load(root)
    labels = {str(x) for x in (doc.get("title"), uid, *(doc.get("labels") or [])) if x}
    I = identity.assign(uid, members, rows, labels, keys.load(root))
    pins = layer.universe_pins(root)
    ucolls = layer.collections(root)
    in_scope = None
    if pages:
        pgs, media, titles, schema_of = pages_mod.build_pages(root, I, pins, ucolls)
        proposed = sorted({tuple(sorted((p["body"], b))) for p in pgs for b in p["also"]})
        in_scope = mark_scope(root, pgs)
    else:
        pgs, media = None, []
        titles, schema_of = pages_mod.titles_of(I, pins)
        proposed = None
    canon_out = identity.canon_rows(I, titles, schema_of)
    report = {
        "title": doc.get("title") or root.name, "uid": uid,
        "built": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages_built": pages,
        "members": {m.name: {"kind": m.kind, "source": str(m.source) if m.kind != layer.SELF else ".",
                             "problem": m.problem,
                             "entities": sum(1 for er in I.ents if er.startswith(m.name + "/"))} for m in members},
        "counts": {"hs": len(I.hs), "pages": len(pgs) if pgs is not None else None,
                   "by_state": dict(Counter(h["state"] for h in I.hs.values())),
                   "by_flag": dict(Counter(f for h in I.hs.values() for f in h["flags"])),
                   "proposed": len(proposed) if proposed is not None else None,
                   "in_scope": in_scope},
        "proposed": [list(p) for p in proposed] if proposed is not None else None,
        "blocked": I.blocked, "warnings": I.warnings, "collections": ucolls,
    }
    _write(root, canon_out, pgs, report, media)
    return report


def mark_scope(root, pgs: list[dict]) -> int:
    """Each page's `scope`: {"in": True, "why": ...} or {"in": False} (context), by scope.yaml.
    -> how many are in scope (all of them when the rules name no seeds)."""
    from hydra import schema
    schema.ensure()
    ends = {s: (d["edge"]["source"], d["edge"]["target"]) for s, d in schema.SCHEMA.items() if d.get("edge")}
    why = scope_mod.compute(pgs, scope_mod.load(root), ends)
    for p in pgs:
        p["scope"] = {"in": True} if why is None else \
            ({"in": True, "why": why[p["body"]]} if p["body"] in why else {"in": False})
    return sum(1 for p in pgs if p["scope"]["in"])


def _write(root: Path, canon_out, pgs, report, media) -> None:
    out = root / layout.UNIVERSE_PARSED
    if pgs is not None and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    dump = lambda rows: "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    (out / "canon.jsonl").write_text(dump(canon_out), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if pgs is None:
        return
    (out / "pages.jsonl").write_text(dump(pgs), encoding="utf-8")
    search = [{"b": p["body"], "t": p["title"], "q": p["qualifier"], "a": p["aliases"], "s": p["schema"],
               **({"k": [f"{k['ns']}:{k['key']}" for k in p["keys"]]} if p.get("keys") else {}),
               **({"x": 1} if not (p.get("scope") or {}).get("in", True) else {})} for p in pgs]
    (out / "search.json").write_text(json.dumps(search, ensure_ascii=False), encoding="utf-8")
    for src, rel in media:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copyfile(src, dest)


def _member_wikis(root: Path) -> list:
    """Each linked member's wiki.yaml — a dir's file, or the pack itself for a packed member —
    their config feeds the wiki merge, so a change there must rebuild these pages."""
    out = []
    try:
        members = (layer.read_manifest(root) or {}).get("members") or {}
    except Exception:
        return out
    for name, spec in members.items():
        try:
            src = Path(layer.member_source(root, name, spec or {}))
        except Exception:
            continue
        out.append(src if src.suffix == ".hydra" else src / "wiki.yaml")
    return out


def pages_current(root) -> bool:
    """Is there a pages build newer than every file the universe build reads?"""
    root = Path(root)
    p = root / layout.UNIVERSE_PARSED / "pages.jsonl"
    if not p.is_file():
        return False
    t = p.stat().st_mtime
    inputs = [root / layout.CANON, root / layout.UNIVERSE_MANIFEST, root / layout.BUILD_YAML,
              root / layout.VERDICTS, root / "wiki.yaml", root / layout.UNIVERSE_WIKI,
              root / layout.INTERNAL / "wiki.yaml",
              *_member_wikis(root),
              *(root / layout.UNIVERSE_DIR / "review").glob("*"),
              *(root / layout.UNIVERSE_COLLECTIONS).glob("*"),
              *(root / layout.SCHEMA_DIR).rglob("*"),          # the schema shapes the infobox and the edges
              *(root / layout.RESOURCES_DIR).rglob("*"),       # icons and images the pages inline
              *(root / layout.RULES_DIR).rglob("*")]           # scope.yaml, keys.yaml... shape the pages
    return all(not f.is_file() or f.stat().st_mtime <= t for f in inputs)
