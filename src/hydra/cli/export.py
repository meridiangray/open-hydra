"""export: the archive, compiled, in formats other tools read.

    hydra-ctl export [<dir> | FILE.hydra] --format ftm|hydra-ftm|csv|graphml
        [-o PATH] [--read declared|generic] [--force] [--ids record|h] [--publish]

`--ids h` (ftm, hydra-ftm): each entity with a canonical id goes out under it,
`H-<12 characters>`, its record ids in `referents`, every link to it rewritten.
`--publish`: the exported entities' computed Hs become published, so they keep
their ids from now on (an export others link to is a promise); it writes the
H-table, so it needs a folder, not a `.hydra`.

`ftm`        the merged entities as standard FollowTheMoney JSON lines: a link
             field holds the id of the record it points at (`member:
             ["consortium:p-elias"]`), as FtM tools and the RDF model behind them
             expect; `referents` and `datasets` kept. For Aleph / OpenAleph,
             nomenklatura and other FtM tools.
`hydra-ftm`  the same entities in hydra's dialect: link fields keep the names
             the records wrote (`member: ["Elias Vaughn"]`). Goes back into a
             hydra collection as it is, since hydra resolves links by name.
`csv`        a folder with `nodes.csv` and `edges.csv` (an edge's first two columns
             are its source and target, as Kuzu's COPY FROM expects; Neo4j and
             Gephi import them too), and `export.yaml` saying what made it.
`graphml`    one GraphML file of the same graph, for Gephi, yEd, Cytoscape.

Every export names the FtM schema it follows by the `ftm:` hash pinned in
`hydra.yaml` (FtM has no format version): printed when it is written, in
`export.yaml` for `csv`, as a graph attribute in `graphml`. The JSON lines carry
no header, so they stay plain FtM.

The graph follows FtM's own convention: every entity that is not a relationship
is a node; each relationship entity (Membership, Ownership…) is an edge between
its two ends, and each link property of a node (Position.organization) an edge
too. hydra adds the tree it chose (`placedUnder`, child to parent, with the
ledger status) and, when the archive has been built (`.hydra/parsed/` present, as in a
built folder or a `.hydra` packed with its build), the merges still open for
review (`sameAs`, with their status); and it
gives each node its caption, position and parent from `--read` (default
declared). A relationship whose ends did not both resolve has no edge; the
count is reported. Read-only: the archive is compiled in memory (as `build`
does, writing nothing), so the export reflects the files as they are now, built
or not; a `.hydra` is read in place. Default output, in the current folder:
`<archive name>.ftm.jsonl`, `<name>.hydra-ftm.jsonl`, `<name>-graph/` or
`<name>.graphml`; an existing one is kept unless `--force`."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from hydra import dates, ingest, layout, resources, schema
from hydra.cli import style
from hydra.cli.pack import _name as archive_name
from hydra.shape import entities as entities_mod

NODE_COLS = ("id", "schema", "caption", "position", "parent", "datasets")
EDGE_COLS = ("source", "target", "type", "id", "directed", "status", "role", "start", "end", "prop")
READS = ("declared", "generic")
NAME_PROPS = ("name", "title", "fileName", "alias")


def _caption(e: dict) -> str:
    props = e.get("properties") or {}
    return next((props[p][0] for p in NAME_PROPS if props.get(p)), e["id"])


FORMATS = ("ftm", "hydra-ftm", "csv", "graphml")


def compile_(root: Path) -> dict:
    """The archive compiled in memory, as `build` does, writing nothing."""
    from hydra import build
    cap: dict = {}
    build.build_archive(root, write=False, capture=cap)
    return cap


def schema_pin(root: Path) -> str:
    """The FtM schema an export follows: the `ftm:` hash pinned in hydra.yaml."""
    m = root / layout.MANIFEST
    doc = (yaml.safe_load(m.read_text(encoding="utf-8")) or {}) if m.is_file() else {}
    return str(doc.get("ftm") or "unpinned")


def graph(ents: list[dict], tree: dict, rows: list[dict],
          open_merges: bool = True, with_sources: bool = False,
          orphans: bool = False) -> tuple[list[dict], list[dict], dict]:
    """-> (nodes, edges, report). `open_merges`: include the `sameAs` questions. `with_sources`
    keeps the evidence layer (Document-family nodes and `sources` links); `orphans` keeps the
    nodes left without an edge once that layer is out."""
    is_edge = lambda s: bool((schema.SCHEMA.get(s) or {}).get("edge"))
    nodes = {}
    for e in ents:
        if is_edge(e["schema"]) or (not with_sources and schema.is_a(e["schema"], "Document")):
            continue
        t = tree.get(e["id"]) or {}
        nodes[e["id"]] = {"id": e["id"], "schema": e["schema"], "caption": t.get("caption") or _caption(e),
                          "position": t.get("position") or "", "parent": t.get("pid") or "",
                          "datasets": ";".join(e.get("datasets") or [])}
    edges, dangling = [], 0
    for e in ents:
        props, pdefs = e.get("properties") or {}, schema.resolve(e["schema"])["props"]
        edge = (schema.SCHEMA.get(e["schema"]) or {}).get("edge")
        if edge:
            ends = [(s, t) for s in props.get(edge["source"]) or [] for t in props.get(edge["target"]) or []
                    if s in nodes and t in nodes and s != t]
            if not ends:
                dangling += 1
            for s, t in ends:
                edges.append({"source": s, "target": t, "type": e["schema"], "id": e["id"],
                              "directed": "false" if edge.get("directed") is False else "true", "status": "",
                              "role": ";".join(props.get("role") or props.get("relationship") or []),
                              "start": dates.earliest(props.get("startDate")) or "",
                              "end": dates.latest(props.get("endDate")) or "", "prop": ""})
            continue
        if e["id"] not in nodes:
            continue
        for p, vals in sorted(props.items()):
            p = ingest.FTM_RENAMES.get(p, p)          # hydra's name for the field (`sources`), not FtM's
            if (pdefs.get(p) or {}).get("type") != "entity" or (p == "sources" and not with_sources):
                continue
            for v in vals:
                if v in nodes and v != e["id"]:
                    edges.append({"source": e["id"], "target": v, "type": f"{e['schema']}.{p}", "id": "",
                                  "directed": "true", "status": "", "role": "", "start": "", "end": "", "prop": p})
    rows = {r["id"]: r for r in rows}
    for rid, n in sorted(tree.items()):
        pl = n.get("placement") or {}
        if n.get("pid") and rid in nodes and n["pid"] in nodes:
            edges.append({"source": rid, "target": n["pid"], "type": "placedUnder", "id": pl.get("ledger") or "",
                          "directed": "true", "status": pl.get("status") or "", "role": n.get("title") or "",
                          "start": "", "end": "", "prop": ""})
    owner = {ref: e["id"] for e in ents for ref in [e["id"], *(e.get("referents") or [])]}
    for r in rows.values() if open_merges else ():
        if r.get("rel") != "sameAs" or r.get("status") in ("auto", "confirmed"):
            continue
        a, b = owner.get(r["a"]), owner.get(r["b"])
        if a in nodes and b in nodes and a != b:
            edges.append({"source": a, "target": b, "type": "sameAs", "id": r["id"], "directed": "false",
                          "status": r["status"], "role": "", "start": "", "end": "", "prop": ""})
    edges.sort(key=lambda x: (x["type"], x["source"], x["target"], x["id"], x["prop"]))
    if not orphans:
        linked = {x["source"] for x in edges} | {x["target"] for x in edges}
        nodes = {i: n for i, n in nodes.items() if i in linked}
    return (sorted(nodes.values(), key=lambda n: n["id"]), edges,
            {"entities": len(ents), "nodes": len(nodes), "edges": len(edges), "unlinked_relationships": dangling})


def _csv(rows, cols) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _graphml(nodes, edges, pin: str) -> str:
    ns = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", ns)
    g_root = ET.Element(f"{{{ns}}}graphml")
    for for_, cols in (("node", NODE_COLS[1:]), ("edge", EDGE_COLS[2:])):
        for c in cols:
            ET.SubElement(g_root, f"{{{ns}}}key", {"id": f"{for_[0]}_{c}", "for": for_, "attr.name": c,
                                                    "attr.type": "string"})
    ET.SubElement(g_root, f"{{{ns}}}key", {"id": "g_ftm_schema", "for": "graph", "attr.name": "ftm_schema",
                                            "attr.type": "string"})
    g = ET.SubElement(g_root, f"{{{ns}}}graph", {"id": "hydra", "edgedefault": "directed"})
    ET.SubElement(g, f"{{{ns}}}data", {"key": "g_ftm_schema"}).text = pin
    for n in nodes:
        el = ET.SubElement(g, f"{{{ns}}}node", {"id": n["id"]})
        for c in NODE_COLS[1:]:
            if n[c]:
                ET.SubElement(el, f"{{{ns}}}data", {"key": f"n_{c}"}).text = n[c]
    for i, e in enumerate(edges):
        attrs = {"id": f"e{i}", "source": e["source"], "target": e["target"]}
        if e["directed"] == "false":
            attrs["directed"] = "false"
        el = ET.SubElement(g, f"{{{ns}}}edge", attrs)
        for c in EDGE_COLS[2:]:
            if e[c]:
                ET.SubElement(el, f"{{{ns}}}data", {"key": f"e_{c}"}).text = e[c]
    ET.indent(g_root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(g_root, encoding="unicode") + "\n"


def by_h(ents: list[dict], hmap: dict) -> list[dict]:
    """Entities under their canonical ids: an entity with an H takes `H-<body>` as its id and
    lists its record ids in `referents` (the canonical-id form FtM tools such as
    nomenklatura read); a link to it is rewritten to match. Relationships keep record ids."""
    out = []
    for e in ents:
        e = dict(e, properties={p: [("H-" + hmap[v]) if v in hmap else v for v in vals]
                                for p, vals in e["properties"].items()})
        if e["id"] in hmap:
            e["referents"] = sorted({e["id"], *(e.get("referents") or [])})
            e["id"] = "H-" + hmap[e["id"]]
        out.append(e)
    return out


def export(root: Path, fmt: str, out: Path, read: str = "declared", ids: str = "record",
           publish: bool = False, with_sources: bool = False, orphans: bool = False) -> dict:
    from hydra.universe import bridge
    cap, pin = compile_(root), schema_pin(root)
    r = cap["resolved"]
    hmap = bridge.body_keys(root, r.survivors, r.records) if ids == "h" or publish else {}
    extra = {}
    if publish:
        from hydra import history
        from hydra.universe import review
        extra["published"] = review.publish(root, sorted(set(hmap.values())))
        history.auto(root, f"export --publish: {extra['published']} H(s) published")
    if fmt in ("ftm", "hydra-ftm"):
        ents = entities_mod.entities(r, links="ids" if fmt == "ftm" else "names")
        if ids == "h":
            ents = by_h(ents, hmap)
        out.write_text("".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in ents),
                       encoding="utf-8")
        return {"entities": len(ents), **({"by h": len({e["id"] for e in ents} & {"H-" + b for b in hmap.values()})}
                                          if ids == "h" else {}), **extra, "ftm schema": pin}
    # open merge questions are review state: exported only from an archive that has been built
    built = (root / layout.BUILD_YAML).is_file()
    nodes, edges, report = graph(entities_mod.entities(cap["resolved"]), cap["reads"][read]["nodes"],
                                 cap["ledger"], open_merges=built, with_sources=with_sources, orphans=orphans)
    if not built:
        report["open_merges"] = "left out"             # an unbuilt archive has no merge questions
    if fmt == "csv":
        out.mkdir(parents=True, exist_ok=True)
        (out / "nodes.csv").write_text(_csv(nodes, NODE_COLS), encoding="utf-8")
        (out / "edges.csv").write_text(_csv(edges, EDGE_COLS), encoding="utf-8")
        (out / "export.yaml").write_text(yaml.safe_dump(
            {"archive": archive_name(root), "ftm_schema": pin, "read": read, **report}, sort_keys=False),
            encoding="utf-8")
    else:
        out.write_text(_graphml(nodes, edges, pin), encoding="utf-8")
    return {**report, **extra, "ftm schema": pin}


def main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl export",
                                 description="Export the last build as FtM entities, graph CSV or GraphML.")
    ap.add_argument("target", nargs="?", help="an archive folder or a .hydra file (default: the active archive)")
    ap.add_argument("--format", required=True, choices=FORMATS,
                    help="ftm: standard FtM (links as ids) · hydra-ftm: links as names · csv · graphml")
    ap.add_argument("-o", "--out", help="where to write (default: named after the archive, here)")
    ap.add_argument("--read", choices=tuple(READS), default="declared")
    ap.add_argument("--force", action="store_true", help="replace an existing output")
    ap.add_argument("--ids", choices=("record", "h"), default="record",
                    help="ftm, hydra-ftm: an entity's id is its record id (default), or its canonical H")
    ap.add_argument("--publish", action="store_true",
                    help="the exported entities' computed Hs become published (others will point at them)")
    ap.add_argument("--with-sources", action="store_true",
                    help="csv, graphml: keep the evidence layer (Document nodes and sources links)")
    ap.add_argument("--orphans", action="store_true",
                    help="csv, graphml: keep nodes that end up with no edge")
    a = ap.parse_args(argv)
    if a.publish and a.target and resources.is_pack(a.target):
        raise SystemExit(f"hydra: --publish writes the archive's H-table; open {a.target} first: init {a.target}")
    root = resources.archive(a.target, read_only=True, built=False)
    name = re.sub(r"[^\w.-]+", "-", Path(a.target).stem if a.target and resources.is_pack(a.target)
                  else archive_name(root)).strip("-.")
    out = Path(a.out) if a.out else Path.cwd() / {"ftm": f"{name}.ftm.jsonl", "hydra-ftm": f"{name}.hydra-ftm.jsonl",
                                                    "csv": f"{name}-graph", "graphml": f"{name}.graphml"}[a.format]
    if out.exists() and not a.force:
        raise SystemExit(f"hydra: {out} exists; --force replaces it")
    report = export(root, a.format, out, a.read, ids=a.ids, publish=a.publish,
                    with_sources=a.with_sources, orphans=a.orphans)
    say(f"{style.verb('Exported')} {style.name(name)} as {a.format} to {style.path(out)}")
    for line in style.across([k.replace("_", " ") for k in report],
                             [f"{v:,}" if isinstance(v, int) else str(v)[:12] if k == "ftm schema" else str(v)
                              for k, v in report.items()]):
        say(line)
    return 0

