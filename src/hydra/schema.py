"""schema.py — the FTM schema loader.

A schema is read from one tree: an archive dir (layered over Hydra's shared
resources when it carries no upstream FTM types of its own), or the resources
alone. Only these paths are schema:

    .hydra/schema/ftm/followthemoney/*.yaml  upstream FTM types (loaded first)
    .hydra/schema/**/*.yaml                  extension types; a name that already exists
                                      is a patch: its props merge onto the type
                                      (loaded second). Except .hydra/schema/norms/ (retired
                                      miniguides, skipped if an old archive has them)
                                      and .hydra/schema/params/ (match/distinct/fold
                                      policy, read by compile/classify.py)
    .hydra/schema/ftm/config/common.yaml     {Schema: [props]}: extra Record-card fields
    .hydra/schema/ftm/config/*.yaml          config docs (findfields, ...) -> config(name)

Everything else (collections/, .hydra/rules/, .hydra/resources/, sources/, .hydra/parsed/) is data.

Beyond the old loader this captures, per property, upstream's `matchable` flag,
and per schema `generated`, schema-level `deprecated` and `temporalExtent`
(classify.py and cycles.py need them).

    schema.load()               # the shared resources (template/)
    schema.load(root=archive)   # an archive, layered over the resources
    schema.resolve("Person")["props"]
"""
from __future__ import annotations
from hydra import layout, resources, yamlcache
import copy
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import yaml


# carrier/structural props FTM mis-features — never entry fields (a common.yaml
# entry still re-includes one; mirrors scribble ftm._NON_ENTRY_PROPS)
_NON_ENTRY_PROPS = {"title", "fileName", "mimeType", "parent", "threadTopic", "amount"}

SCHEMA: dict[str, dict] = {}
CONFIG: dict[str, dict] = {}
LOADED: dict = {"source": None, "key": None}
_CACHE: dict = {}


def _clean_featured(feat) -> list[str]:
    return [str(f).split("#", 1)[0].strip() for f in feat or []]


def _is_yaml(p: str) -> bool:
    return p.endswith((".yaml", ".yml"))


def _role(path: str) -> str | None:
    """File path -> schema role. Schema files live under the schema dir."""
    p = path
    if p in (layout.HINTS, layout.DEFAULT_POSITIONS, layout.POSITIONS, layout.VERDICTS, layout.DIRECTION):
        return None  # authored rules, not types

    if p.startswith(f"{layout.SCHEMA_DIR}/"):
        rel = p[len(f"{layout.SCHEMA_DIR}/"):]

        if rel.startswith("norms/"):
            return None  # normative miniguides, not type schemas

        if rel.startswith("params/"):
            return None  # <Type>.param.yaml — match/distinct/fold policy,
                        # read by compile/classify.py, not a type schema

        if rel == "ftm/config/common.yaml":
            return "common"
        if rel.startswith("ftm/followthemoney/") and rel.count("/") == 2 and _is_yaml(rel):
            return "core"
        if rel.startswith("ftm/config/") and rel.count("/") == 2 and _is_yaml(rel):
            return "config"

        if _is_yaml(rel):
            return "extra"

    return None


def _ingest(target: dict, doc: dict) -> None:
    """Merge one yaml doc ({Type: body}) into `target`; an existing name is a
    patch — its properties (and display lists) merge onto the type."""
    for name, body in (doc or {}).items():
        if not isinstance(body, dict):
            continue
        props = {}
        for pname, pdef in (body.get("properties") or {}).items():
            pdef = pdef if isinstance(pdef, dict) else {}
            props[pname] = {"label": pdef.get("label", pname),
                            "type": pdef.get("type", "string"),
                            "hidden": bool(pdef.get("hidden", False)),
                            "matchable": bool(pdef.get("matchable", True)),
                            "range": pdef.get("range"),
                            "reverse": (pdef.get("reverse") or {}).get("label"),
                            "revname": (pdef.get("reverse") or {}).get("name"),
                            }
        if name in target:
            target[name]["properties"].update(props)
            for k in ("featured", "required", "caption", "common"):
                target[name][k] += [p for p in _clean_featured(body.get(k))
                                    if p not in target[name][k]]
            continue
        edge = body.get("edge") if isinstance(body.get("edge"), dict) else None
        target[name] = {"extends": body.get("extends") or [],
                        "featured": _clean_featured(body.get("featured")),
                        "required": _clean_featured(body.get("required")),
                        "caption": _clean_featured(body.get("caption")),
                        "common": _clean_featured(body.get("common")),
                        "label": body.get("label", name),
                        "abstract": bool(body.get("abstract", False)),
                        "generated": bool(body.get("generated", False)),
                        "deprecated": bool(body.get("deprecated", False)),
                        "temporalExtent": body.get("temporalExtent") or {},
                        "edge": ({"source": edge.get("source"),
                                  "target": edge.get("target"),
                                  "label": edge.get("label", ""),
                                  "directed": edge.get("directed", True)}
                                 if edge else None),
                        "properties": props}


def compose(files: dict[str, bytes | str]) -> tuple[dict, dict]:
    """{path: content} of one tree -> (schema, config). Pure — no globals."""
    sch, cfg, common = {}, {}, {}
    parse = lambda b: yaml.safe_load(b.decode("utf-8") if isinstance(b, bytes) else b) or {}
    by_role = {}
    for p in sorted(files):
        r = _role(p)
        if r:
            by_role.setdefault(r, []).append(p)
    for p in by_role.get("core", []) + by_role.get("extra", []):
        _ingest(sch, parse(files[p]))
    for p in by_role.get("config", []):
        cfg[Path(p).stem] = parse(files[p])
    for p in by_role.get("common", []):
        common = parse(files[p])
    for name, props in (common or {}).items():
        if name in sch:
            sch[name]["common"] += [x for x in _clean_featured(props)
                                    if x not in sch[name]["common"]]
    return sch, cfg


_SCHEMA_TREES = (layout.SCHEMA_DIR,)   # the only places a role can be


def _role_paths(root: Path) -> dict[str, Path]:
    """Every schema-role file under `root`. Walks only the schema trees (os.walk
    knows file types from the listing, so no per-file stat is needed here)."""
    root, out = Path(root), {}
    for tree in _SCHEMA_TREES:
        for d, _dirs, files in os.walk(root / tree):
            for name in files:
                fp = Path(d) / name
                rel = fp.relative_to(root).as_posix()
                if _role(rel):
                    out[rel] = fp
    return out


def _stamp(paths: dict[str, Path]) -> tuple:
    """(relpath, size, mtime) of every file: a change to any of them changes
    the stamp, so a cached result is reused only while nothing moved."""
    out = []
    for rel, fp in sorted(paths.items()):
        st = yamlcache.stat(fp)
        out.append((rel, st.st_size, st.st_mtime_ns))
    return tuple(out)


def _has_core(paths) -> bool:
    return any(_role(p) == "core" for p in paths)


_SEED: dict[str, tuple] = {}     # resolved resource dir -> (paths, stamp), once per process


def _seed_layer(seed: Path) -> tuple[dict[str, Path], tuple]:
    """The shared resources' schema files and their stamp. Read once per process:
    the resources are not expected to change while hydra runs (an archive's own
    files are still checked on every load)."""
    k = str(Path(seed).resolve())
    if k not in _SEED:
        paths = _role_paths(seed)
        _SEED[k] = (paths, _stamp(paths))
    return _SEED[k]


def _is_seed(root, seed) -> bool:
    return bool(seed) and Path(root).resolve() == Path(seed).resolve()


def load(root=None) -> None:
    """Populate SCHEMA/CONFIG from `root` (an archive dir), else from Hydra's
    shared resources (`template/`). An archive that carries no upstream FTM types
    is layered over the resources file by file: an archive file replaces the
    resource file at the same path, and an extension type in either still
    patches the type it names. Composed once per set of file stamps and cached."""
    seed = resources.seed_dir()
    if root is None or _is_seed(root, seed):
        layers, stamp = _seed_layer(seed) if seed else ({}, ())
        source = str(seed) if seed else None
    else:
        own = _role_paths(Path(root))
        layers, stamp = {}, ()
        if not _has_core(own) and seed:
            layers, stamp = dict(_seed_layer(seed)[0]), _seed_layer(seed)[1]
        layers.update(own)
        stamp = stamp + _stamp(own)
        source = str(root)
    key = ("dir", stamp)
    if key not in _CACHE:
        make = lambda: list(compose({rel: fp.read_bytes() for rel, fp in layers.items()}))
        own_archive = root is not None and not _is_seed(root, seed)
        _CACHE[key] = tuple(yamlcache.derived(root, "schema", stamp, make) if own_archive else make())
    sch, cfg = copy.deepcopy(_CACHE[key])
    from hydra.ingest import FTM_RENAMES          # FtM's names for fields are hydra's inside: `proof` is `sources`
    for sc in sch.values():
        props = sc.get("properties") or {}
        for ftm, ours in FTM_RENAMES.items():
            if ftm in props:
                d = props.pop(ftm)
                props.setdefault(ours, d)
        if sc.get("featured"):
            sc["featured"] = list(dict.fromkeys(FTM_RENAMES.get(p, p) for p in sc["featured"]))
    src = {"source": source, "key": key}
    SCHEMA.clear(); SCHEMA.update(sch)
    CONFIG.clear(); CONFIG.update(cfg)
    LOADED.update(src)
    ancestors.cache_clear()
    _RESOLVED.clear()


def ensure():
    if not SCHEMA:
        load()


@lru_cache(maxsize=None)
def ancestors(name: str) -> tuple[str, ...]:
    """Extends chain, self first."""
    ensure()
    seen, order = set(), []
    def walk(n):
        if not n or n in seen or n not in SCHEMA:
            return
        seen.add(n); order.append(n)
        for anc in SCHEMA[n].get("extends") or []:
            walk(anc)
    walk(name)
    return tuple(order)


def is_a(name: str, ancestor: str) -> bool:
    return name == ancestor or ancestor in ancestors(name)


_RESOLVED: dict[str, dict] = {}


def resolve(name: str) -> dict:
    """Merged prop map + featured (self-first). Cached until the next load();
    callers only read it."""
    ensure()
    if name in _RESOLVED:
        return _RESOLVED[name]
    _RESOLVED[name] = _resolve(name)
    return _RESOLVED[name]


def _resolve(name: str) -> dict:
    props, featured, fseen, claimed = {}, [], set(), set()
    for n in ancestors(name):
        sc = SCHEMA.get(n)
        if not sc:
            continue
        for fp in sc["featured"]:
            if fp not in fseen:
                fseen.add(fp); featured.append(fp)
        for pname, pdef in sc["properties"].items():
            if pname not in claimed:
                claimed.add(pname); props[pname] = pdef
    return {"props": props, "featured": featured}


def _own_base(schema_name: str, props: dict) -> list[str]:
    """The schema's OWN derived common set (no ancestors): own featured ∪
    required ∪ caption ∪ own entity-typed props, filtered to non-hidden."""
    s = SCHEMA.get(schema_name) or {}
    out, seen = [], set()
    for p in s["featured"] + s["required"] + s["caption"]:
        if p in props and not props[p].get("hidden") and p not in seen:
            seen.add(p); out.append(p)
    for p in s["properties"]:
        pd = props.get(p)
        if pd and pd["type"] == "entity" and not pd.get("hidden") and p not in seen:
            seen.add(p); out.append(p)
    return out


def own_common(schema_name: str) -> list[str]:
    """THIS schema's common set only (no ancestor merge): derived own base
    minus _NON_ENTRY_PROPS, plus the schema's common.yaml entries (an entry
    re-includes a suppressed prop)."""
    ensure()
    s = SCHEMA.get(schema_name) or {}
    props = resolve(schema_name)["props"]
    out = [p for p in _own_base(schema_name, props) if p not in _NON_ENTRY_PROPS]
    seen = set(out)
    for p in s["common"]:
        if p in props and not props[p].get("hidden") and p not in seen:
            seen.add(p); out.append(p)
    return out


def common(schema_name: str) -> list[str]:
    """The common entry fields a Record card shows: own_common merged up the
    `extends` chain (self first, deduped), filtered non-hidden."""
    ensure()
    props = resolve(schema_name)["props"]
    out, seen = [], set()
    for n in ancestors(schema_name):
        for p in own_common(n):
            if p in props and not props[p].get("hidden") and p not in seen:
                seen.add(p); out.append(p)
    return out


# The config plane: every file whose content steers the compiler. `_role`
# selects .hydra/schema/ (norms excluded — docs, never loaded); the default
# positions file joins it, and direction.yaml too. positions.yaml, hints.yaml and
# .hydra/review/ are subject-authored or written by review — they stay out,
# so two archives built from the same config hash identically whatever their
# subject declares.
CONFIG_PATHS = (layout.DEFAULT_POSITIONS, layout.DIRECTION)


def in_config_scope(path: str) -> bool:
    """True when `path` belongs to the config plane hashed by config_hash."""
    return (_role(path) is not None or path in CONFIG_PATHS
            or (path.startswith(layout.PARAMS_DIR + "/") and path.endswith(".param.yaml")))


def config_files(root) -> dict[str, Path]:
    """Every file under `root` in the config plane ({relpath: path}), found by
    walking only the folders it can be in."""
    root = Path(root)
    out = dict(_role_paths(root))
    for rel in CONFIG_PATHS:
        if (root / rel).is_file():
            out[rel] = root / rel
    params = root / layout.PARAMS_DIR
    if params.is_dir():
        for fp in params.glob("*.param.yaml"):
            out[f"{layout.PARAMS_DIR}/{fp.name}"] = fp
    return out


def archive_config_hash(root) -> str:
    """config_hash over `root`'s config files, kept in the archive's cache while
    none of them change."""
    files = config_files(root)
    return yamlcache.derived(root, "config_hash", _stamp(files),
                             lambda: config_hash({rel: fp.read_bytes() for rel, fp in files.items()}))


def config_hash(files: dict) -> str:
    """sha256 over the in-scope files of one tree ({path: bytes|str}), sorted
    relpath + bytes, CRLF-normalized — a hash generalized to the whole config
    plane. Recorded in .hydra/parsed/build.yaml as `config`."""
    h = hashlib.sha256()
    for p in sorted(files):
        if not in_config_scope(p):
            continue
        raw = files[p]
        if raw is None:
            continue
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        h.update(p.encode() + b"\0" + raw.replace(b"\r\n", b"\n"))
    return h.hexdigest()
