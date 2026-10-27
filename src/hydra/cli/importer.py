"""import: load FtM records, or a graph export, into the archive as a collection.

    hydra-ctl import [<dir>] <path> --format ftm|hydra-ftm|csv|graphml
        [--name <collection>] [--force] [--no-build]

The formats `export` writes, read back:

`ftm`        standard FollowTheMoney JSON (a list, `{"entities": [...]}`, or JSON
             lines), as Aleph, OpenSanctions and other FtM tools write it.
`hydra-ftm`  the same with links written as names, as `export --format hydra-ftm` does.
             Both are copied into collections/ exactly as they are; loading reads
             them like any collection (FtM's `proof` is `sources` inside hydra).
`csv`        a folder with `nodes.csv` and `edges.csv`, as `export --format csv` writes.
`graphml`    a GraphML file, as `export --format graphml` writes.
             A graph carries each entity's id, type and name, and the links: each
             relationship edge becomes its relationship record (with role and dates),
             each link-property edge the property. The edges hydra derives
             (`placedUnder`, `sameAs`) are left out: a build makes them again.
             Written to collections/ as FtM JSON lines.

The collection is named after the file (`case.ftm.jsonl` -> `case`, `case-graph/`
-> `case`) unless `--name`. One that exists is kept unless `--force`. Rebuilds
unless --no-build."""
from __future__ import annotations

import argparse
import csv
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from hydra import layout, resources, schema
from hydra.cli import style
from hydra.cli.export import FORMATS, NAME_PROPS
from hydra.ingest import FTM_RENAMES, parse_records

DERIVED = ("placedUnder", "sameAs")              # edges a build makes, not data
ENDINGS = (".jsonl", ".json", ".jsonld", ".ftm", ".hydra-ftm", ".csv", ".graphml", "-graph")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def collection_name(path: Path) -> str:
    """`case.hydra-ftm.jsonl` -> `case`, `case-graph` -> `case`."""
    name = path.name
    while True:
        end = next((e for e in ENDINGS if name.lower().endswith(e) and len(name) > len(e)), None)
        if not end:
            return name
        name = name[: -len(end)]


def _graph_rows(path: Path, fmt: str) -> tuple[list[dict], list[dict]]:
    """(node rows, edge rows) with export's column names."""
    if fmt == "csv":
        if not path.is_dir() or not (path / "nodes.csv").is_file():
            raise SystemExit(f"hydra: {path} is not a csv export (a folder with nodes.csv and edges.csv)")
        read = lambda f: list(csv.DictReader((path / f).open(encoding="utf-8", newline=""))) \
            if (path / f).is_file() else []
        return read("nodes.csv"), read("edges.csv")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise SystemExit(f"hydra: {path} is not GraphML: {e}")
    ns = {"g": root.tag[1:].split("}")[0]} if root.tag.startswith("{") else {"g": ""}
    q = (lambda t: f"g:{t}") if ns["g"] else (lambda t: t)
    keys = {k.get("id"): k.get("attr.name") for k in root.findall(q("key"), ns)}
    data = lambda el: {keys.get(d.get("key"), d.get("key")): d.text or "" for d in el.findall(q("data"), ns)}
    graph = root.find(q("graph"), ns)
    if graph is None:
        raise SystemExit(f"hydra: {path} has no graph")
    nodes = [{"id": n.get("id"), **data(n)} for n in graph.findall(q("node"), ns)]
    edges = [{"source": e.get("source"), "target": e.get("target"), **data(e)} for e in graph.findall(q("edge"), ns)]
    return nodes, edges


def from_graph(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], dict]:
    """Node and edge rows -> (FtM records, counts). Names, types and links only."""
    schema.ensure()
    recs: dict[str, dict] = {}
    skipped = {"derived edges": 0, "unknown types": 0}
    for n in nodes:
        sname = n.get("schema") or ""
        if sname not in schema.SCHEMA:
            skipped["unknown types"] += 1
            continue
        props = schema.resolve(sname)["props"]
        field = next((p for p in NAME_PROPS if p in props), None)
        recs[n["id"]] = {"id": n["id"], "schema": sname,
                         "properties": {field: [n["caption"]]} if field and n.get("caption") else {}}
    for e in edges:
        kind = e.get("type") or ""
        if kind in DERIVED:
            skipped["derived edges"] += 1
            continue
        edge = (schema.SCHEMA.get(kind) or {}).get("edge")
        if edge:                                   # a relationship record, one row per pair of its ends
            rid = e.get("id") or f"{kind}:{e['source']}>{e['target']}"
            r = recs.setdefault(rid, {"id": rid, "schema": kind, "properties": {}})
            p = r["properties"]
            for prop, v in ((edge["source"], e["source"]), (edge["target"], e["target"])):
                if v not in p.setdefault(prop, []):
                    p[prop].append(v)
            for prop, v in (("role", e.get("role")), ("startDate", e.get("start")), ("endDate", e.get("end"))):
                for x in (v or "").split(";") if prop == "role" else [v]:
                    if x and x not in p.setdefault(prop, []):
                        p[prop].append(x)
            for prop in [k for k, v in p.items() if not v]:
                del p[prop]
        elif "." in kind and e.get("source") in recs:      # a link property: `Person.sources`
            prop = FTM_RENAMES.get(e.get("prop") or kind.split(".", 1)[1], e.get("prop") or kind.split(".", 1)[1])
            vals = recs[e["source"]]["properties"].setdefault(prop, [])
            if e["target"] not in vals:
                vals.append(e["target"])
        else:
            skipped["unknown types"] += 1
    return list(recs.values()), skipped


def main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl import",
                                 usage="hydra-ctl import [<dir>] <path> --format ftm|hydra-ftm|csv|graphml "
                                       "[--name N] [--force] [--no-build]",
                                 description="Load FtM records, or a graph export, into the archive as a collection.")
    ap.add_argument("words", nargs="+", metavar="[dir] path", help="an archive (optional), then the file or folder")
    ap.add_argument("--format", required=True, choices=FORMATS,
                    help="ftm: standard FtM · hydra-ftm: links as names · csv: an export's folder · graphml")
    ap.add_argument("--name", default="", help="the collection's name (default: the file's)")
    ap.add_argument("--force", action="store_true", help="replace a collection of that name")
    ap.add_argument("--no-build", action="store_true", help="do not rebuild")
    a = ap.parse_args(argv)
    words = list(a.words)
    lead = words.pop(0) if len(words) > 1 and resources.names_archive(words[0]) else None
    if len(words) != 1:
        style.usage(ap.format_usage().rstrip())
    root, src = resources.archive(lead), Path(words[0]).expanduser()
    if not src.exists():
        raise SystemExit(f"hydra: {src} not found")
    name = a.name or collection_name(src)
    if not NAME.match(name):
        raise SystemExit(f"hydra: '{name}' cannot name a collection (letters, digits, - and _); use --name")
    cdir = root / layout.COLLECTIONS_DIR
    there = [f for f in (cdir / f"{name}.json", cdir / f"{name}.jsonld") if f.is_file()]
    if there and not a.force:
        raise SystemExit(f"hydra: collection '{name}' exists; --force replaces it, or --name names another")
    if a.format in ("ftm", "hydra-ftm"):
        if not src.is_file():
            raise SystemExit(f"hydra: {src} is not a file")
        text = src.read_text(encoding="utf-8")
        try:
            n = len(parse_records(text))
        except (json.JSONDecodeError, AttributeError) as e:
            raise SystemExit(f"hydra: {src} does not read as FtM records: {e}")
        skipped: dict = {}
    else:
        schema.load(root=root)
        recs, skipped = from_graph(*_graph_rows(src, a.format))
        n = len(recs)
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    if not n:
        raise SystemExit(f"hydra: {src} holds no records with an id")
    for f in there:
        f.unlink()
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{name}.json").write_text(text, encoding="utf-8")
    say(f"{style.verb('Imported')} {style.name(src.name)} as collection {style.name(name)}: "
        f"{n:,} {'record' if n == 1 else 'records'}"
        + "".join(f", {v} {k} left out" for k, v in skipped.items() if v))
    if not a.no_build:
        from hydra import build
        say(build.report(root, build.build_archive(root), verb="Rebuilt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
