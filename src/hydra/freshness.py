"""freshness.py — whether an archive's last build still stands.

After a build, its inputs and outputs are fingerprinted (each file's size and
mtime, plus hydra's own version and files) and kept in the archive's cache.
`build` compares the current fingerprint and, when nothing moved, keeps the last
build instead of running it again. Kept apart from build.py so that this check
imports almost nothing."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hydra import layout, schema, yamlcache
from hydra.review import verdicts as vd

_CODE: list = []                                  # this process's code stamp, once


def input_files(root) -> dict[str, Path]:
    """Every file a build reads, and the files it writes: when none of them
    changed (and the code did not), building again would give the same result."""
    root = Path(root)
    out = dict(schema.config_files(root))
    for rel in (layout.MANIFEST, layout.POSITIONS, layout.HINTS, layout.DEFAULT_POSITIONS, layout.DIRECTION):
        out[rel] = root / rel
    for f in vd.files(root):
        out[f.relative_to(root).as_posix()] = f
    for d in (layout.COLLECTIONS_DIR, layout.SOURCE_ENTRIES, layout.PARSED_DIR, layout.RESOURCES_DIR):
        for dirpath, _dirs, names in os.walk(root / d):
            for n in names:
                fp = Path(dirpath) / n
                out[fp.relative_to(root).as_posix()] = fp
    return out


def _stamps(paths) -> list:
    """(size, mtime) of each path, or None when missing. Stat'ed in parallel: on a
    slow file system (a Windows drive under WSL) each one waits ~1 ms, and the
    waits overlap."""
    def one(p):
        try:
            st = os.stat(p)
            return [st.st_size, st.st_mtime_ns]
        except OSError:
            return None
    paths = list(paths)
    if len(paths) < 32:
        return [one(p) for p in paths]
    with ThreadPoolExecutor(max_workers=16) as ex:
        return list(ex.map(one, paths))


def _code_stamp() -> list:
    """The hydra version and the stamps of its own files (code and template), so a
    new install or an edited working tree builds again."""
    if not _CODE:
        from hydra import __version__
        pkg = Path(__file__).resolve().parent
        files = sorted(Path(d) / n for d, dirs, names in os.walk(pkg)
                       if "__pycache__" not in d and "/cache" not in d.replace(os.sep, "/")
                       for n in names)
        _CODE.append([__version__, _stamps(files)])
    return _CODE[0]


def fingerprint(root) -> list:
    files = input_files(root)
    rels = sorted(files)
    return [_code_stamp(), list(zip(rels, _stamps(files[r] for r in rels)))]


def up_to_date(root) -> bool:
    """True when the last build's inputs and outputs are exactly as it left them."""
    root = Path(root)
    last = yamlcache.recall(root, "last_build")
    return bool(last) and (root / layout.BUILD_YAML).is_file() \
        and json.loads(json.dumps(fingerprint(root))) == last
