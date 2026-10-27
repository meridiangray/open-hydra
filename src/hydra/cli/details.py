"""details: one screen on an archive or a `.hydra` file, from its last build.

    hydra-ctl details [<dir> | FILE.hydra] [--format text|json]

Name and subject, when it was built, its collections and prefixes, records and
entities by type, the size of the tree, the questions still open, and the
issues found. It reads three small files (`hydra.yaml`, `.hydra/parsed/build.yaml`,
and for a `.hydra` its `hydra-pack.json`), straight out of a pack without
unpacking it, so it is quick at any size. It never builds: an archive with no
build says so. On a folder it also warns when a collection or rule file is newer
than the build. `todo` lists the open questions, `tree` draws the hierarchy,
`claims summary` counts where values came from."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import yaml

from hydra import layout, resources
from hydra.cli import style
from hydra.cli.pack import PACK_INDEX

OPEN = ("proposed", "unresolved", "conflict", "confirmed-stale")


def _reader(target: Path):
    """-> read(rel) -> text or None, for a folder or a .hydra (members read singly)."""
    if resources.is_pack(target):
        z = zipfile.ZipFile(target)
        names = set(z.namelist())
        return lambda rel: z.read(rel).decode("utf-8") if rel in names else None
    return lambda rel: (target / rel).read_text(encoding="utf-8") if (target / rel).is_file() else None


def _newer_than_build(root: Path, built: str) -> list[str]:
    try:
        when = datetime.fromisoformat(built).timestamp()
    except (TypeError, ValueError):
        return []
    from hydra import freshness                   # the files a build reads, as `build` decides staleness
    return sorted(rel for rel, p in freshness.input_files(root).items()
                  if not rel.startswith(layout.PARSED_DIR + "/") and rel != layout.COLLECTIONS_MANIFEST
                  and p.is_file() and p.stat().st_mtime > when + 1)


def collect(target) -> dict:
    target = Path(target)
    read = _reader(target)
    meta = yaml.safe_load(read(layout.MANIFEST) or "") or {}
    out = {"archive": str(target), "name": meta.get("name") or target.stem, "subject": meta.get("subject")}
    if resources.is_pack(target):
        idx = json.loads(read(PACK_INDEX) or "{}")
        out["pack"] = {"bytes": target.stat().st_size, "files": len(idx.get("files") or {}),
                       "with_build": bool(idx.get("parsed"))}
    b = yaml.safe_load(read(layout.BUILD_YAML) or "") or {}
    if not b:
        out["built"] = None
        return out
    ledger = b.get("ledger") or {}
    open_ = {kind: sum(n for st, n in counts.items() if st in OPEN) for kind, counts in ledger.items()}
    out.update({
        "built": b.get("built"),
        "collections": {c: {k: v.get(k) for k in ("prefix", "records", "claims", "in_others", "citations")}
                        for c, v in (b.get("collections") or {}).items()},
        "records": b.get("records"), "entities": b.get("entities"), "claims": b.get("claims"),
        "schemas": b.get("schemas") or {},
        "reads": {k: {x: v.get(x) for x in ("nodes", "roots", "positioned")} for k, v in (b.get("reads") or {}).items()},
        "open": {k: n for k, n in open_.items() if n},
        "automatic": {k: (counts or {}).get("auto", 0) for k, counts in ledger.items()},
        "issues": b.get("issue_counts") or {},
    })
    if not resources.is_pack(target):
        out["newer_than_build"] = _newer_than_build(target, b.get("built"))
    return out


def _n(x) -> str:
    return f"{x:,}" if isinstance(x, int) else "-"


TYPES_SHOWN = 8
REVIEW = ("merges", "placements", "references")
GUTTER = 6


def _table(header: list[str], rows: list[list], first: str = "name", w0: int = 0) -> list[list[tuple[str, str]]]:
    """Rows as (text, style) lines: the first column left-aligned in `first`
    style (at least `w0` wide, so stacked tables line up), the rest
    right-aligned numbers; the header dim."""
    cells = [header] + [[str(r[0])] + [_n(x) if not isinstance(x, str) else x for x in r[1:]] for r in rows]
    w = [max(len(c[i]) for c in cells) for i in range(len(header))]
    w[0] = max(w[0], w0)
    line = lambda c, kinds: [(f"{c[0]:<{w[0]}}", kinds[0])] + [
        (f"   {x:>{w[i + 1]}}", kinds[i + 1]) for i, x in enumerate(c[1:])]
    out = [line(cells[0], ["aside"] * len(header))]
    for c in cells[1:]:
        out.append(line(c, [first] + [""] * (len(header) - 1)))
    return out


def _pairs(rows: list[tuple[str, str]], width: int = 0) -> list[list[tuple[str, str]]]:
    """key / value lines: the key dim, padded to the widest."""
    w = max([len(k) for k, _ in rows] + [width])
    return [[(f"{k:<{w}}", "aside"), ("   ", ""), (v, "")] for k, v in rows]


def render(d: dict, width: int | None = None) -> list[str]:
    """Two columns when the terminal is wide enough (the archive on the left,
    what is open and the tree on the right), else one under the other."""
    subj = d.get("subject") or {}
    head = [("name", d["name"])] + ([("subject", f"{subj.get('label')}   {subj.get('type')}")]
                                    if subj.get("label") else [])
    if d.get("pack"):
        p = d["pack"]
        head.append(("pack", f"{p['bytes'] / 2**20:.1f} MB   " + ("with its build" if p["with_build"] else "without its build")))
    if not d.get("built"):
        return [style.styled(x) for x in _pairs(head + [("built", "not yet")])]
    left = _pairs([x for x in head if x[0] == "pack"] + [("records", _n(d["records"])),
                   ("entities", _n(d.get("entities"))), ("claims", _n(d.get("claims")))])
    for f in (d.get("newer_than_build") or [])[:3]:
        left.append([("changed ", "note"), ("   ", ""), (f, "note")])
    if len(d.get("newer_than_build") or []) > 3:
        left.append([("changed ", "note"), ("   ", ""), (f"{len(d['newer_than_build']) - 3} more", "note")])
    cols = d.get("collections") or {}
    shown_prefix = any(v.get("prefix") not in (None, c) for c, v in cols.items())
    header = ["collection"] + (["prefix"] if shown_prefix else []) + ["records", "claims", "in others", "citations"]
    rows = [[c] + ([str(v.get("prefix") or "")] if shown_prefix else [])
            + [v.get("records"), v.get("claims"), v.get("in_others"), v.get("citations")] for c, v in cols.items()]
    rows.sort(key=lambda r: -(r[-4] or 0))
    left += [[]] + _table(header, rows)
    sch = list((d.get("schemas") or {}).items())
    rest = sch[TYPES_SHOWN:]
    rows = [[s, v.get("entities"), v.get("records")] for s, v in sch[:TYPES_SHOWN]]
    if rest:
        rows.append([f"{len(rest)} more", sum(v.get("entities") or 0 for _, v in rest),
                     sum(v.get("records") or 0 for _, v in rest)])
    left += [[]] + _table(["type", "entities", "records"], rows)

    auto, open_ = d.get("automatic") or {}, d.get("open") or {}
    kinds = [k for k in REVIEW if k in auto or k in open_] + [k for k in {**auto, **open_} if k not in REVIEW]
    reads = d.get("reads") or {}
    order = sorted(reads, key=lambda r: r != "declared")             # declared first
    w0 = max(len(x) for x in ["review", "tree", "issues", "warnings"] + kinds + list(reads))
    right = _table(["review", "automatic", "open"], [[k, auto.get(k, 0), open_.get(k, 0)] for k in kinds], w0=w0)
    for line in right[1:]:                                        # an open count above 0 stands out
        if line[-1][0].strip() not in ("0", "-"):
            line[-1] = (line[-1][0], "note")
    right += [[]] + _table(["tree", "nodes", "roots", "positioned"],
                           [[r, reads[r]["nodes"], reads[r]["roots"], reads[r]["positioned"]]
                            for r in order], w0=w0)
    iss = d.get("issues") or {}
    right += [[]] + _table(["issues", "count"], [[label, iss.get(lv, 0)] for lv, label in
                                                 (("error", "errors"), ("warning", "warnings"), ("info", "info"))],
                           w0=w0)
    for line in right[-3:-1]:                                     # errors and warnings above 0
        if line[-1][0].strip() != "0":
            line[-1] = (line[-1][0], "note")

    plain = lambda parts: "".join(x for x, _ in parts)
    lw, rw = max(len(plain(x)) for x in left), max(len(plain(x)) for x in right)
    width = width or shutil.get_terminal_size((120, 24)).columns
    built = d["built"].replace("T", " ").replace("+00:00", " UTC")
    title = [(d["name"], "name")] + ([("   ", ""), (subj.get("label"), "")] if subj.get("label") else [])
    if lw + GUTTER + rw <= width:
        pad = max(lw + GUTTER + rw - len(plain(title)) - len("built   ") - len(built), 3)
        out = [style.styled(title + [(" " * pad, ""), ("built   ", "aside"), (built, "")]), ""]
        for i in range(max(len(left), len(right))):
            a = left[i] if i < len(left) else []
            b = right[i] if i < len(right) else []
            out.append((style.styled(a) + " " * (lw + GUTTER - len(plain(a))) + style.styled(b)).rstrip())
        return out
    out = [style.styled(title), style.styled(_pairs([("built", built)])[0]), ""]
    return out + [style.styled(x) for x in left] + [""] + [style.styled(x) for x in right]


def main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl details", description="One screen on an archive or .hydra file.")
    ap.add_argument("target", nargs="?", help="an archive folder or a .hydra file (default: the active archive)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(argv)
    target = Path(a.target) if a.target and resources.is_pack(a.target) else resources.archive(a.target)
    d = collect(target)
    if (a.format == "json"):
        say(json.dumps(d, indent=1, ensure_ascii=False))
    else:
        for line in render(d):
            say(line)
    return 0
