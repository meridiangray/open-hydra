"""members.py — adding and refreshing a universe's members.

    embed    snapshot an archive (folder or .hydra) into universe/members/<name>.hydra: it travels
    link     a member outside the file, pinned to its SHA-256 (its changes are reported, not hidden)
    refresh  re-pin a linked member to its current bytes, or replace an embedded snapshot
    remove   take a member out (its Hs stay in the table; their records are gone: orphaned)
"""
from __future__ import annotations

import os
from pathlib import Path

from hydra import layout
from hydra.universe import layer


def _check_name(doc, name):
    if name in doc["members"]:
        raise SystemExit(f"hydra: there is already a member {name}")
    if not name or "/" in name or name == layer.SELF or name.startswith("."):
        raise SystemExit(f"hydra: {name!r} cannot name a member")


def _rel(path: Path, base: Path) -> str:
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:                   # another drive on Windows: kept absolute
        return str(path)


def embed(root, archive, name: str) -> Path:
    from hydra.cli import pack as hpack
    doc = layer.read_manifest(root)
    _check_name(doc, name)
    dest = Path(root) / layout.UNIVERSE_MEMBERS / f"{name}{hpack.SUFFIX}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = Path(archive)
    if archive.is_file():
        dest.write_bytes(archive.read_bytes())
    else:                                # its own history and builds stay home: the snapshot is its data
        hpack.pack(archive, dest, with_parsed=False, force=True, with_history=False)
    doc["members"][name] = {"pack": f"members/{dest.name}"}
    layer.write_manifest(root, doc)
    return dest


def link(root, path, name: str) -> dict:
    doc = layer.read_manifest(root)
    _check_name(doc, name)
    path = Path(path).resolve()
    if not path.exists():
        raise SystemExit(f"hydra: {path} does not exist")
    spec = {"path": _rel(path, layer.udir(root).resolve()), "sha256": layer.fingerprint(path)}
    doc["members"][name] = spec
    layer.write_manifest(root, doc)
    return spec


def refresh(root, name: str, archive=None) -> str:
    doc = layer.read_manifest(root)
    spec = doc["members"].get(name)
    if spec is None or name == layer.SELF:
        raise SystemExit(f"hydra: no member {name} to refresh")
    if spec.get("pack"):
        if not archive:
            raise SystemExit("hydra: an embedded member is a snapshot: give the archive to embed again")
        del doc["members"][name]
        layer.write_manifest(root, doc)
        embed(root, archive, name)
        return "embedded again"
    spec["sha256"] = layer.fingerprint(layer.member_source(root, name, spec))
    layer.write_manifest(root, doc)
    return "pinned to its current bytes"


def remove(root, name: str) -> None:
    doc = layer.read_manifest(root)
    spec = doc["members"].pop(name, None)
    if spec is None or name == layer.SELF:
        raise SystemExit(f"hydra: no member {name} to remove")
    layer.write_manifest(root, doc)
    if spec.get("pack"):
        p = layer.member_source(root, name, spec)
        if p.is_file():
            p.unlink()
