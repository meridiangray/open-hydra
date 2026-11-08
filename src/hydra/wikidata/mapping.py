"""mapping.py — the map: .hydra/rules/wikidata.yaml (the archive's own, else the one hydra ships).

    load(root)  -> {"classes": {Q: schema}, "ignore": {P}, "common": {...}, "properties": {schema: {...}},
                    "relationships": {schema: {P: {...}}}}   (every section present, maybe empty)
    path(root)  -> the file read

See the file itself for what each section says."""
from __future__ import annotations

from pathlib import Path

from hydra import layout, resources, yamlcache


def path(root=None) -> Path:
    own = Path(root) / layout.WIKIDATA if root else None
    return own if own and yamlcache.is_file(own) else resources.TEMPLATE / layout.WIKIDATA


def load(root=None) -> dict:
    f = path(root)
    doc = yamlcache.load(f) if yamlcache.is_file(f) else {}
    doc = doc if isinstance(doc, dict) else {}
    return {
        "classes": {str(k): str(v) for k, v in (doc.get("classes") or {}).items()},
        "ignore": {str(p) for p in doc.get("ignore") or []},
        "common": doc.get("common") or {},
        "properties": doc.get("properties") or {},
        "relationships": doc.get("relationships") or {},
    }
