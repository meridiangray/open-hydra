"""yamlcache.py — an archive's YAML files, parsed once and kept in `.hydra/cache/`.

`load(path)` returns what `yaml.safe_load` would. Inside an archive the parsed
result is kept in `.hydra/cache/yaml.json` under the file's (size, mtime): while
those are unchanged the file is not read again, and an edited file is parsed
afresh the next time it is loaded. The schema, params and rules hardly ever
change, so a build parses almost nothing. Verdicts are not loaded through here
(they change with every answer).

Entries are stored as JSON, not pickle: a `.hydra` pack can come from someone
else, and JSON cannot run code. A file whose parsed content does not survive
JSON unchanged (a date, a non-string key) is simply parsed each time. The cache
is derived: deleting `.hydra/cache/` costs one slower build. `pack` leaves it
out; a cache that cannot be written (a read-only folder) is skipped silently.

`derived(root, name, stamp, make)` keeps a value computed from many files (the
composed schema, the config hash) under the stamps it was made from."""
from __future__ import annotations

import atexit
import copy
import json
import os
import stat as stat_mod
from contextlib import contextmanager
from pathlib import Path

import yaml

try:                                                  # libyaml's C parser when installed
    from yaml import CSafeLoader as _Loader
except ImportError:                                   # pragma: no cover
    from yaml import SafeLoader as _Loader

from hydra import layout

CACHE_DIR = f"{layout.INTERNAL}/cache"
_FILE = "yaml.json"
_FORMAT = 2
_STORES: dict[str, dict] = {}                         # archive root -> {"files": {...}, "derived": {...}, "dirty": bool}
_FROZEN: dict | None = None                            # during a build: path -> stat result (or None)
_ROOTS: dict[str, Path | None] = {}                    # folder -> the archive it is in
_TEMPLATE = Path(__file__).resolve().parent / "template"   # the shipped template: never cached into


@contextmanager
def frozen():
    """While a build runs, each file is stat'ed once: its files cannot change
    under it, and on a slow file system (a Windows drive under WSL) the repeated
    checks were most of a small build's time. Outside a build every call looks."""
    global _FROZEN
    outer = _FROZEN
    _FROZEN = {} if outer is None else outer
    try:
        yield
    finally:
        _FROZEN = outer


def stat(path):
    """os.stat of `path`, or None when it is missing; once per path during a build."""
    key = os.path.abspath(path)
    if _FROZEN is not None and key in _FROZEN:
        return _FROZEN[key]
    try:
        got = os.stat(key)
    except (FileNotFoundError, NotADirectoryError):
        got = None
    if _FROZEN is not None:
        _FROZEN[key] = got
    return got


def is_file(path) -> bool:
    st = stat(path)
    return st is not None and stat_mod.S_ISREG(st.st_mode)


def is_dir(path) -> bool:
    st = stat(path)
    return st is not None and stat_mod.S_ISDIR(st.st_mode)


def parse(text: str):
    return yaml.load(text, Loader=_Loader)


def _archive_of(folder: Path) -> Path | None:
    """The archive `folder` is in: the nearest folder at or above it holding both
    hydra.yaml and .hydra/ (None for the shipped template). Memoized per folder."""
    k = str(folder)
    if k not in _ROOTS:
        found = None
        for d in (folder, *folder.parents):
            if is_file(d / layout.MANIFEST) and is_dir(d / layout.INTERNAL):
                found = d
                break
        _ROOTS[k] = None if found is not None and found == _TEMPLATE else found
    return _ROOTS[k]


def _store(root: Path) -> dict:
    k = str(root)
    if k not in _STORES:
        doc = {}
        try:
            doc = json.loads((root / CACHE_DIR / _FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if not isinstance(doc, dict) or doc.get("format") != _FORMAT:
            doc = {}
        _STORES[k] = {"files": doc.get("files") or {}, "derived": doc.get("derived") or {}, "dirty": False}
    return _STORES[k]


def _stamp(st) -> list:
    return [st.st_size, st.st_mtime_ns]


def load(path):
    """yaml.safe_load of the file at `path`, from the cache while it is unchanged."""
    path = Path(os.path.abspath(path))
    root = _archive_of(path.parent)
    if root is None:
        return parse(path.read_text(encoding="utf-8"))
    st = stat(path)
    if st is None:
        raise FileNotFoundError(path)
    store, rel = _store(root), path.relative_to(root).as_posix()
    hit = store["files"].get(rel)
    if hit and hit[0] == _stamp(st):
        return copy.deepcopy(hit[1])                  # a copy: callers may edit what they get
    doc = parse(path.read_text(encoding="utf-8"))
    try:
        kept = json.loads(json.dumps(doc, ensure_ascii=False))
        if kept == doc:
            store["files"][rel] = [_stamp(st), kept]
            store["dirty"] = True
    except (TypeError, ValueError):
        pass                                          # not JSON-shaped: parsed each time
    return doc


def derived(root, name: str, stamp, make):
    """The value `make()` computes from many files, kept under `name` while
    `stamp` (any JSON value naming those files' stamps) is unchanged. Outside an
    archive it is just computed."""
    root = _archive_of(Path(os.path.abspath(root)))
    if root is None:
        return make()
    store, key = _store(root), json.loads(json.dumps(stamp))
    hit = store["derived"].get(name)
    if hit and hit[0] == key:
        return hit[1]
    value = make()
    store["derived"][name] = [key, value]
    store["dirty"] = True
    return value


def remember(root, name: str, value) -> None:
    """Keep `value` under `name` in the archive's cache (no-op outside an archive)."""
    root = _archive_of(Path(os.path.abspath(root)))
    if root is not None:
        store = _store(root)
        store["derived"][name] = ["", json.loads(json.dumps(value))]      # as it will read back
        store["dirty"] = True


def recall(root, name: str):
    """What `remember` kept under `name`, or None."""
    root = _archive_of(Path(os.path.abspath(root)))
    hit = _store(root)["derived"].get(name) if root is not None else None
    return hit[1] if hit else None


def save() -> None:
    """Write every changed cache (at exit, and after a build)."""
    for k, store in _STORES.items():
        if not store["dirty"]:
            continue
        target = Path(k) / CACHE_DIR / _FILE
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            store["files"] = {rel: v for rel, v in store["files"].items() if os.path.isfile(Path(k) / rel)}
            tmp = target.with_name(f"{_FILE}.{os.getpid()}.part")
            tmp.write_text(json.dumps({"format": _FORMAT, "files": store["files"], "derived": store["derived"]},
                                      ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, target)
            store["dirty"] = False
        except OSError:
            pass


atexit.register(save)
