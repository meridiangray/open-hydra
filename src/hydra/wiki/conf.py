"""conf.py — where the wiki's config comes from.

Each member's `wiki.yaml` is a default, merged in manifest order (a member's own
file speaks first); `universe/wiki.yaml` overrides per key — a mapping merges
key by key, anything else replaces. An archive with no universe layer just gets
its own `wiki.yaml` back. `hydra.yaml` `collections: {name: {wiki: {...}}}` then
gives one collection's pages their own overrides on top of that.
"""
from __future__ import annotations

from pathlib import Path

from hydra import layout, resources, yamlcache


def _merge(a: dict, b: dict) -> dict:
    """b over a, key by key: mappings merge their entries, scalars and lists replace."""
    out = dict(a)
    for k, v in b.items():
        out[k] = {**out[k], **v} if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def _member_docs(root) -> list[dict]:
    """Every member's root wiki.yaml, in manifest order (unresolvable members are skipped)."""
    from hydra.universe import layer
    docs = []
    try:
        members = (layer.read_manifest(root) or {}).get("members") or {}
    except Exception:
        members = {}
    for name, spec in members.items():
        try:
            src = Path(layer.member_source(root, name, spec or {}))
        except Exception:
            continue
        f = src / "wiki.yaml"
        if not f.is_file() and resources.is_pack(src):
            f = resources._view(src, built=False) / "wiki.yaml"
        if f.is_file():
            docs.append(yamlcache.load(f) or {})
    return docs


def conf_doc(root) -> dict:
    """The wiki config a universe renders with: members' wiki.yaml first, universe/wiki.yaml over."""
    conf = {}
    for doc in _member_docs(root):
        conf = _merge(conf, doc)
    u = Path(root) / layout.UNIVERSE_WIKI
    if u.is_file():
        conf = _merge(conf, yamlcache.load(u) or {})
    return conf


def collection_conf(root, conf: dict) -> dict:
    """{collection: conf}: a collection's `wiki:` overrides in hydra.yaml, merged over `conf`."""
    meta = yamlcache.load(Path(root) / layout.MANIFEST) or {}
    return {name: _merge(conf, (spec or {}).get("wiki") or {})
            for name, spec in (meta.get("collections") or {}).items()
            if isinstance(spec, dict) and spec.get("wiki")}
