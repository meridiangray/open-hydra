"""resources.py — where Hydra's shared resources live, and which archive is active.

The resources are the package's own `template/`: the vendored FTM schema, the shipped
extension types, rules and param files. `schema.load()` reads them directly, and
an archive without its own upstream FTM types is layered over them.

Activation is a marker file (`.hydra-activate`) naming one archive, found like
`.git`: the nearest one in the current folder or an ancestor wins."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hydra import layout, yamlcache

TEMPLATE = Path(__file__).resolve().parent / "template"
RECIPES = Path(__file__).resolve().parent / "recipes"     # ready-made ladders, never copied into an archive
ACTIVATE = ".hydra-activate"


def recipes() -> dict[str, Path]:
    """The hierarchy recipes hydra ships, by name: whole ladders an archive opts
    into by adding a recipe's lines to its own positions.yaml."""
    return {p.stem: p for p in sorted(RECIPES.glob("*.yaml"))}


def seed_dir() -> Path | None:
    """The shared resources, or None when the template carries no FTM schema."""
    return TEMPLATE if (TEMPLATE / layout.FTM_DIR / "followthemoney").is_dir() else None


def archive_prefix(root) -> str | None:
    """The archive's own id prefix (`prefix:` in hydra.yaml), or None."""
    from hydra.ingest import valid_prefix
    p = Path(root) / layout.MANIFEST
    doc = (yamlcache.load(p) or {}) if p.is_file() else {}
    got = doc.get("prefix") if isinstance(doc, dict) else None
    return got if valid_prefix(got) else None


def is_archive(p) -> bool:
    p = Path(p)
    return p.is_dir() and (p / layout.MANIFEST).is_file()


def names_archive(word) -> bool:
    """True when a command's first word is an archive folder or a `.hydra` file
    (taken as the archive), not a search word or a file."""
    return bool(word) and (is_archive(word) or is_pack(word))


def _find_marker(start=None) -> Path | None:
    d = Path(start or os.getcwd()).resolve()
    while True:
        if (d / ACTIVATE).is_file():
            return d / ACTIVATE
        if d.parent == d:
            return None
        d = d.parent


def activated(start=None) -> Path | None:
    """The archive named by the nearest activation marker, or None."""
    m = _find_marker(start)
    doc = (yaml.safe_load(m.read_text(encoding="utf-8")) or {}) if m else {}
    return Path(doc["archive"]) if doc.get("archive") else None


def activate(archive, start=None) -> Path:
    """Write a marker in `start` (default: the current folder) naming `archive`."""
    p = Path(archive).expanduser().resolve()
    if not is_archive(p):
        raise ValueError(f"{p} is not an archive (no {layout.MANIFEST})")
    m = Path(start or os.getcwd()).resolve() / ACTIVATE
    m.write_text(yaml.safe_dump({"archive": str(p), "activated": datetime.now(timezone.utc)
                                 .isoformat(timespec="seconds")}, sort_keys=False),
                 encoding="utf-8")
    return m


def deactivate(start=None) -> Path:
    """Remove the nearest activation marker."""
    m = _find_marker(start)
    if not m:
        raise ValueError(f"no active archive ({ACTIVATE} not found)")
    m.unlink()
    return m


# ---- defaults: the template's config files, as an archive carries them -----

# name -> the archive paths it covers, in the order a person reads them
DEFAULTS = {
    "generic": (layout.DEFAULT_POSITIONS,),
    "hierarchy": (layout.POSITIONS,),
    "hints": (layout.HINTS,),
    "direction": (layout.DIRECTION,),
    "collate": (layout.COLLATE,),
    "params": tuple(sorted(f"{layout.PARAMS_DIR}/{p.name}"
                           for p in (TEMPLATE / layout.PARAMS_DIR).glob("*.param.yaml"))),
    "artifact": (layout.ARTIFACT,),
}
# The hierarchy defaults can be switched off (the build reads them as empty);
# the others are what the compiler itself runs on.
SWITCHABLE = ("generic", "hierarchy", "hints")
OFF_KEY = "defaults_off"


def defaults_off_doc(doc: dict) -> set[str]:
    return {n for n in (doc.get(OFF_KEY) or []) if n in SWITCHABLE}


def defaults_off(root) -> set[str]:
    """The hierarchy defaults `hydra.yaml` switches off (`defaults_off: [...]`)."""
    m = Path(root) / layout.MANIFEST
    return defaults_off_doc((yamlcache.load(m) or {}) if yamlcache.is_file(m) else {})


def is_off(root, rel: str) -> bool:
    """True when the file at `rel` is a hierarchy default switched off."""
    return any(rel in DEFAULTS[n] for n in defaults_off(root))


def default_state(root, name: str) -> dict:
    """One default against the template: `{name, state, files: {path: state}}`,
    a file being `default`, `changed` or `missing`; the default is the worst of
    its files, or `off` when switched off."""
    root = Path(root)
    files = {}
    for rel in DEFAULTS[name]:
        mine, shipped = root / rel, TEMPLATE / rel
        files[rel] = ("missing" if not mine.is_file() else
                      "default" if mine.read_bytes() == shipped.read_bytes() else "changed")
    states = set(files.values())
    state = next((s for s in ("missing", "changed") if s in states), "default")
    return {"name": name, "state": "off" if name in defaults_off(root) else state,
            "content": state, "files": files}


# ---- packed archives (.hydra) ----------------------------------------------

PACK_SUFFIX = ".hydra"
_VIEWS: list = []                        # temporary folders of packs opened read-only


def is_pack(p) -> bool:
    p = Path(p)
    return p.suffix == PACK_SUFFIX and p.is_file()


def warn(msg: str) -> None:
    from hydra.cli import style
    style.warn(msg)


def ensure_built(root, label=None) -> Path:
    """Build an archive that has no build yet (a pack made without `.hydra/parsed/`):
    warned once, then the command reads the fresh build."""
    root = Path(root)
    if not (root / layout.BUILD_YAML).is_file():
        from hydra import build
        if not any(record_files(root)):
            raise SystemExit(f"hydra: {root} {build.NOTHING}")
        warn(f"{label} carries no build (packed without .hydra/parsed/); building it aside for this command"
             if label else f"no build in {root} yet; building it now")
        build.build_archive(root)
    return root


def _view(pack_file, built: bool = True) -> Path:
    """A `.hydra` opened for reading: unpacked into a temporary folder that is
    removed when the command ends, built there if the pack carries no build.
    Nothing is written beside the file."""
    from hydra.cli.pack import unpack
    tmp = tempfile.TemporaryDirectory(prefix="hydra-view-")
    _VIEWS.append(tmp)                   # lives until the interpreter exits
    dest, _ = unpack(pack_file, Path(tmp.name) / Path(pack_file).stem)
    return ensure_built(dest, label=pack_file) if built else dest


def archive(path=None, *, read_only: bool = False, built: bool = True) -> Path:
    """The archive a command works on: `path` if given, else the active archive,
    else the current folder if it is one. A `.hydra` file is accepted by commands
    that only read (`read_only`); one that writes is told to open it first. A
    folder given or activated must be an archive: nothing is read from, built
    in or written to any other folder.
    `built=False`: a pack is not built for the command (it compiles on its own)."""
    if path and is_pack(path):
        if not read_only:
            raise SystemExit(f"hydra: {path} is a packed archive; open it first: init {path}")
        return _view(path, built)
    if path:
        if not is_archive(path):
            raise SystemExit(f"hydra: {path} is not an archive (no {layout.MANIFEST})")
        return Path(path)
    act = activated()
    if act:
        if not is_archive(act):
            raise SystemExit(f"hydra: the active archive {act} is gone or no longer an archive "
                             f"(no {layout.MANIFEST}); activate another, or deactivate")
        return act
    if is_archive(Path.cwd()):
        return Path.cwd()
    raise SystemExit("hydra: no archive given, none active (activate <dir>), "
                     "and the current folder is not one")


# ---- reading an archive's files ---------------------------------------------------


def record_files(root) -> tuple[list[Path], list[Path]]:
    """(the collection files, the source entry files) a build reads."""
    root = Path(root)
    grab = lambda d: sorted(list(d.glob("*.json")) + list(d.glob("*.jsonld")))
    return ([f for f in grab(root / layout.COLLECTIONS_DIR) if f.name != "manifest.json"],
            grab(root / layout.SOURCE_ENTRIES))


def read_jsonl(path) -> list[dict]:
    """One dict per non-empty line; [] when there is no such file."""
    path = Path(path)
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if path.is_file() else []


def declared_nodes(root) -> dict:
    """The last build's nodes, declared read; {} when there is no build."""
    p = Path(root) / layout.READS["declared"]
    return (json.loads(p.read_text(encoding="utf-8")).get("nodes") or {}) if p.is_file() else {}


def review_rows(root) -> dict[str, dict]:
    """The last build's review rows (sameAs, placements, references...), by id."""
    root = Path(root)
    return {r["id"]: r for r in read_jsonl(root / layout.IDENTICAL_JSONL) + read_jsonl(root / layout.LEDGER_JSONL)}
