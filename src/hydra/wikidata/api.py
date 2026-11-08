"""api.py — asking Wikidata: items and properties, cached on disk.

    fetch(qids, cache)       -> {Q: item}: the items asked for, then every item their claims point at
    describe(pids, cache)    -> {P: {label, description, datatype, formatter}}
    label(item)              -> the English label

Answers are kept one file each under `<cache>/items/` and `<cache>/props/`, so a second run asks
nothing. `wbgetentities` takes 50 ids at a time; 40 are sent."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.wikidata.org/w/api.php"
UA = "hydra-ctl (https://github.com/meridiangray/open-hydra)"
BATCH = 40
PAUSE = 0.3                               # seconds between requests: Wikidata asks clients to be gentle


def _get(params: dict) -> dict:
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(f"hydra: could not reach Wikidata: {getattr(e, 'reason', e)}") from None


def label(item) -> str:
    """The English label. Wikidata keeps a name that is alike in every language under `mul`."""
    labels = (item or {}).get("labels") or {}
    return (labels.get("en") or labels.get("mul") or {}).get("value", "")


def _cached(folder: Path, ids, ask) -> dict[str, dict]:
    """{id: answer} for ids: from files in folder, the rest from ask(batch) -> {id: answer} (then saved)."""
    folder.mkdir(parents=True, exist_ok=True)
    out, need = {}, []
    for i in ids:
        f = folder / f"{i}.json"
        if f.is_file():
            out[i] = json.loads(f.read_text(encoding="utf-8"))
        else:
            need.append(i)
    for n in range(0, len(need), BATCH):
        for i, answer in ask(need[n:n + BATCH]).items():
            out[i] = answer
            (folder / f"{i}.json").write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
        time.sleep(PAUSE)
    return out


def _entities(ids, props) -> dict[str, dict]:
    got = _get({"action": "wbgetentities", "ids": "|".join(ids), "format": "json",
                "props": props, "languages": "en|mul"})
    return {i: e for i, e in (got.get("entities") or {}).items() if "missing" not in e}


def _linked(item) -> set[str]:
    """The items a claim, or one of its qualifiers, points at."""
    out = set()
    for claims in (item.get("claims") or {}).values():
        for c in claims:
            snaks = [c["mainsnak"]] + [s for qs in (c.get("qualifiers") or {}).values() for s in qs]
            for s in snaks:
                v = (s.get("datavalue") or {}).get("value")
                if isinstance(v, dict) and str(v.get("id", "")).startswith("Q"):
                    out.add(v["id"])
    return out


def fetch(qids, cache, refs: bool = True) -> dict[str, dict]:
    """{Q: item} for the items asked for and, with refs, every item their claims point at."""
    items_dir = Path(cache) / "items"
    ask = lambda batch: _entities(batch, "labels|aliases|descriptions|claims")
    out = _cached(items_dir, list(qids), ask)
    if refs:
        wanted = sorted(set().union(*(_linked(out[q]) for q in qids if q in out)) - set(out))
        out.update(_cached(items_dir, wanted, ask))
    return out


def describe(pids, cache) -> dict[str, dict]:
    """{P: {label, description, datatype, formatter}}. `formatter` is the property's URL pattern
    (`https://viaf.org/viaf/$1`) when it is an identifier, else ''."""
    def ask(batch):
        out = {}
        for pid, e in _entities(batch, "labels|descriptions|datatype|claims").items():
            fmt = [c["mainsnak"]["datavalue"]["value"] for c in (e.get("claims") or {}).get("P1630", [])
                   if c["mainsnak"].get("datavalue")]
            out[pid] = {"label": label(e), "datatype": e.get("datatype", ""), "formatter": fmt[0] if fmt else "",
                        "description": ((e.get("descriptions") or {}).get("en") or {}).get("value", "")}
        return out
    return _cached(Path(cache) / "props", list(pids), ask)
