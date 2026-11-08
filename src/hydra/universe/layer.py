"""layer.py — the universe layer of an archive, and its members.

An archive folder (or the `.hydra` packed from it) carries two parallel layers:

    hydra.yaml, collections/, session/, .hydra/    the archive layer
    universe/                                      the universe layer
        universe.yaml          title, uid, members
        canon.jsonl            the H-table: written by review and publishing, never by a build
        review/verdicts.yaml   universe-level caption pins (cap-<H body>)
        collections/*.yaml     curated lists of Hs: {title, members: [H-...]}
        members/*.hydra        embedded members (snapshots that travel in the file)
        .parsed/               what a universe build writes, and the only thing it writes

A member is where records come from:

    self: {}                                   the archive layer of this same folder
    reg:  {pack: members/reg.hydra}            embedded, relative to universe/
    saud: {path: ../../saud, sha256: ...}      linked, relative to universe/, pinned to its bytes

Every member is read only: compiled in memory with the archive build
(`write=False`), so its own merges, rejections and caption pins hold. A record
is named across the universe as `<member>/<record id>`.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hydra import layout, resources, schema
from hydra.review import ids as hids
from hydra.review import verdicts as hvd
from hydra.universe import hid

SELF = "self"
IMAGE_KINDS = ("portraits", "thumbs", "logos")
IMAGE_KINDS_ONE = {"portraits": "portrait", "thumbs": "thumb", "logos": "logo"}      # what a page calls them
IMAGE_DIRS = (layout.RESOURCES_DIR, "", "session")      # where an image path in hints is looked for, in order


def udir(root) -> Path:
    return Path(root) / layout.UNIVERSE_DIR


def is_universe(root) -> bool:
    return (Path(root) / layout.UNIVERSE_MANIFEST).is_file()


def read_manifest(root) -> dict:
    p = Path(root) / layout.UNIVERSE_MANIFEST
    if not p.is_file():
        raise SystemExit(f"hydra: {root} has no universe layer; add one: hydra-ctl universe init {root}")
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    doc.setdefault("members", {})
    return doc


def write_manifest(root, doc: dict) -> None:
    (Path(root) / layout.UNIVERSE_MANIFEST).write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def new_uid() -> str:
    return "".join(secrets.choice(hid.ALPHABET) for _ in range(8))


def init(root, title: str = "") -> Path:
    """Add a universe layer to an archive: a new uid and the archive itself as `self`."""
    root = Path(root)
    if not resources.is_archive(root):
        raise SystemExit(f"hydra: {root} is not an archive (no {layout.MANIFEST})")
    if is_universe(root):
        raise SystemExit(f"hydra: {root} already has a universe layer")
    for d in ("review", "collections"):
        (udir(root) / d).mkdir(parents=True, exist_ok=True)
    name = (yaml.safe_load((root / layout.MANIFEST).read_text(encoding="utf-8")) or {}).get("name") or root.name
    write_manifest(root, {"title": title or name, "uid": new_uid(), "members": {SELF: {}}})
    (root / layout.CANON).touch()
    return udir(root)


def fingerprint(path: Path) -> str:
    """SHA-256 of a member's bytes: the file for a pack, else the records and decisions of a folder."""
    path = Path(path)
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    h = hashlib.sha256()
    parts = [path / layout.MANIFEST, *sorted((path / layout.COLLECTIONS_DIR).rglob("*")),
             *sorted((path / layout.REVIEW_DIR).rglob("*")), *sorted((path / layout.RULES_DIR).rglob("*"))]
    for p in parts:
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def member_source(root, name: str, spec: dict) -> Path:
    if name == SELF:
        return Path(root)
    rel = spec.get("pack") or spec.get("path")
    if not rel:
        raise SystemExit(f"hydra: universe member {name} has neither pack nor path")
    return (udir(root) / rel).resolve()


@dataclass
class Member:
    """One member compiled in memory: what the universe build reads from it."""
    name: str
    kind: str                       # self | pack | path
    source: Path
    root: Path | None = None        # the folder it was compiled from (a temporary view for a pack)
    problem: str = ""               # why it could not be read; empty when it was
    warnings: list = field(default_factory=list)
    entities: dict = field(default_factory=dict)    # survivor id -> FtM entity (links as ids)
    records: dict = field(default_factory=dict)     # record id -> survivor id
    raw: dict = field(default_factory=dict)         # record id -> parsed record
    nodes: dict = field(default_factory=dict)       # survivor id -> declared-read node
    claims: list = field(default_factory=list)
    stubs: dict = field(default_factory=dict)       # stub id -> its name (a link to no record)
    ambiguous: set = field(default_factory=set)     # link values that name several records (a review question)
    apart: set = field(default_factory=set)         # record pairs its review decided are two entities
    pinned: set = field(default_factory=set)        # survivor ids whose caption this archive pinned
    schemas: dict = field(default_factory=dict)     # schema -> {edge, featured, ancestors, props, label}
    positions: dict = field(default_factory=dict)   # the declared read's position ladder

    def ref(self, rid: str) -> str:
        return f"{self.name}/{rid}"

    def survivor(self, rid: str) -> str | None:
        s = self.records.get(rid)
        return s if s in self.entities else None


def schema_info(names) -> dict:
    out = {}
    for s in names:
        if s not in schema.SCHEMA:
            continue
        r = schema.resolve(s)
        out[s] = {"edge": schema.SCHEMA[s].get("edge"),
                  "featured": list(r.get("featured") or []),
                  "ancestors": sorted(schema.ancestors(s)),
                  "label": schema.SCHEMA[s].get("label") or s,
                  "props": {p: {"label": d.get("label") or p, "type": d.get("type"), "hidden": d.get("hidden")}
                            for p, d in r["props"].items()}}
    return out


def from_capture(m: Member, cap: dict) -> Member:
    """Fill a member from a compiled archive (`build_archive(write=False, capture=...)`)."""
    from hydra.shape import entities as hentities
    r = cap["resolved"]
    m.entities = {e["id"]: e for e in hentities.entities(r)}
    m.records = {rec["id"]: hids.survivor(r.survivors, rec["id"]) for rec in r.records}
    m.raw = {rec["id"]: rec for rec in r.records}
    m.stubs = {rec["id"]: (rec.get("properties", {}).get("name") or [rec["id"]])[0]
               for rec in r.records if rec.get("_stub")}
    m.ambiguous = {row["value"] for row in r.ref_rows or []
                   if row.get("status") != "confirmed" and len(row.get("candidates") or []) > 1}
    m.apart = {frozenset((row["a"], row["b"])) for row in cap.get("ledger") or []     # its own "different" answers
               if row.get("rel") == "sameAs" and row.get("status") == "rejected"}
    declared = cap["reads"]["declared"]
    m.nodes = declared["nodes"]
    m.claims = declared["claims"]
    m.positions = dict((declared.get("rules") or {}).get("positions") or {})
    ladder = m.root / layout.PARSED_YAML                  # the compiled ladder, titles included
    if ladder.is_file():
        doc = yaml.safe_load(ladder.read_text(encoding="utf-8")) or {}
        for name, d in (doc.get("positions") or {}).items():
            v = dict(m.positions.get(name) or {})         # not the read's own dict: it is written next
            v.setdefault("titles", (d or {}).get("titles") or [])
            m.positions[name] = v
    verdicts, _ = hvd.load(m.root)
    for k in verdicts:
        if k.startswith("cap-") and not k.startswith("cap-H-"):
            m.pinned.add(m.records.get(k[4:], k[4:]))
    m.schemas = schema_info({e["schema"] for e in m.entities.values()})
    return m


def load_member(root, name: str, spec: dict, capture: dict | None = None) -> Member:
    """Compile one member read-only. `capture`: the archive already compiled (for `self`)."""
    from hydra.cli import export as hexport
    src = member_source(root, name, spec)
    kind = SELF if name == SELF else ("pack" if spec.get("pack") else "path")
    m = Member(name=name, kind=kind, source=src)
    if not src.exists():
        m.problem = f"{src} is missing"
        return m
    if kind == "path" and spec.get("sha256") and fingerprint(src) != spec["sha256"]:
        m.warnings.append(f"member {name} changed since it was linked; `universe refresh {name}` re-pins it")
    try:
        m.root = resources._view(src, built=False) if resources.is_pack(src) else src
        cap = capture if capture is not None else hexport.compile_(m.root)
    except SystemExit as e:              # hydra reports an unreadable archive this way
        m.problem = str(e).removeprefix("hydra: ")
        return m
    except Exception as e:               # NothingToBuild and the like: a member with nothing in it
        m.problem = str(e)
        return m
    return from_capture(m, cap)


def load_members(root, doc: dict, capture: dict | None = None) -> list:
    return [load_member(root, n, spec or {}, capture if n == SELF else None) for n, spec in doc["members"].items()]


def collections(root) -> dict:
    """Universe collections: {slug: {title, members: [H bodies]}}."""
    out = {}
    for f in sorted((Path(root) / layout.UNIVERSE_COLLECTIONS).glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        bodies = []
        for x in doc.get("members") or []:
            try:
                bodies.append(hid.body(x))
            except ValueError:
                pass
        out[f.stem] = {"title": doc.get("title") or f.stem, "members": bodies}
    return out


def universe_pins(root) -> dict:
    p = Path(root) / layout.UNIVERSE_VERDICTS
    doc = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else {}
    return {k[4:]: str(v) for k, v in doc.items() if str(k).startswith("cap-")}


def set_pin(root, key: str, value) -> None:
    p = Path(root) / layout.UNIVERSE_VERDICTS
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.is_file() else {}
    if value is None:
        doc.pop(key, None)
    else:
        doc[key] = value
    p.write_text(yaml.safe_dump(doc, sort_keys=True, allow_unicode=True), encoding="utf-8")


def read_parsed(root, name: str, missing=None):
    p = Path(root) / layout.UNIVERSE_PARSED / name
    if not p.is_file():
        if missing is not None:
            return missing
        raise SystemExit(f"hydra: {p} not found; build the universe first: hydra-ctl universe build {root}")
    if name.endswith(".jsonl"):
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(p.read_text(encoding="utf-8"))


def h_of_records(root) -> dict[str, str]:
    """{record id of `self`: H body} from the last universe build (plus any newer
    decisions in universe/canon.jsonl): how the archive build finds the H of a record."""
    from hydra.universe import table
    out = {}
    for row in read_parsed(root, "canon.jsonl", missing=[]):
        if row.get("redirect"):
            continue
        for ref in row.get("members") or []:
            member, _, rid = ref.partition("/")
            if member == SELF:
                out[rid] = row["body"]
    rows = table.load(root)
    for body, row in rows.items():
        if table.follow(rows, body) != body:
            continue
        for ref in row.get("members") or []:
            member, _, rid = ref.partition("/")
            if member == SELF:
                out[rid] = body
    return out
