"""wikidata: read Wikidata items into the archive by its map, and find what the map does not read yet.

    hydra-ctl wikidata import [<dir>] Q… [--name <collection>] [--force] [--no-build]
    hydra-ctl wikidata unread [<dir>] Q… [--limit N] [--all]
    hydra-ctl wikidata prop P…

`import`   fetches the items (and the items they point at) from wikidata.org, reads them by
           .hydra/rules/wikidata.yaml into FtM records, writes them as a collection (`wikidata` unless
           --name), and says what it copied, made into records, left out and did not read. A record
           carries its key (`upstream: wikidata:Q42`), so it merges with any record that holds the key.
           A collection that exists is kept unless --force. Rebuilds unless --no-build.
`unread`   changes nothing: the claims on those items the map has no rule for, grouped as fields they
           could fill, ids on other sites, and the rest, so a person can nominate them.
`prop`     what a Wikidata property code means.

Answers from Wikidata are kept in the archive's .hydra/cache/wikidata/, so a repeat asks nothing."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from hydra import layout, resources, schema
from hydra.cli import style
from hydra.wikidata import api, mapping, nominate, read, report

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
QID = re.compile(r"^Q\d+$", re.I)
PID = re.compile(r"^P\d+$", re.I)


def _root(lead):
    """The archive, or None when none is given or active (unread and prop work without one)."""
    try:
        return resources.archive(lead)
    except SystemExit:
        if lead:
            raise
        return None


def _cache(root) -> Path:
    return Path(root) / layout.CACHE_DIR / "wikidata" if root else Path.home() / ".cache" / "hydra" / "wikidata"


def _codes(words, pattern, what):
    bad = [w for w in words if not pattern.match(w)]
    if bad:
        raise SystemExit(f"hydra: {', '.join(bad)} {'is' if len(bad) == 1 else 'are'} not {what}")
    return [w.upper() for w in words]


def main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl wikidata",
                                 usage="hydra-ctl wikidata import|unread [<dir>] Q… [options] | prop P…",
                                 description="Read Wikidata items into the archive by its map.")
    ap.add_argument("action", choices=["import", "unread", "prop"])
    ap.add_argument("words", nargs="+", metavar="[dir] Q… | P…", help="an archive (optional), then item ids; or property ids")
    ap.add_argument("--name", default="wikidata", help="import: the collection's name (default: wikidata)")
    ap.add_argument("--force", action="store_true", help="import: replace a collection of that name")
    ap.add_argument("--no-build", action="store_true", help="import: do not rebuild")
    ap.add_argument("--limit", type=int, default=25, help="unread: rows per group (default 25)")
    ap.add_argument("--all", action="store_true", help="unread: every row")
    a = ap.parse_args(argv)
    words = list(a.words)
    if a.action == "prop":
        root = _root(None)
        say("\n".join(report.props(api.describe(_codes(words, PID, "a property code (P…)"), _cache(root)))))
        return 0

    lead = words.pop(0) if len(words) > 1 and resources.names_archive(words[0]) else None
    root = _root(lead)
    if a.action == "import" and root is None:
        raise SystemExit("hydra: no archive given, none active, and the current folder is not one")
    qids = _codes(words, QID, "an item id (Q…)")
    if root:
        schema.load(root=root)
    rules = mapping.load(root)
    items = api.fetch(qids, _cache(root))
    records, rep = read.convert(items, qids, rules)

    if a.action == "unread":
        props = api.describe(sorted({pid for _, pid in rep["unread"]}), _cache(root))
        groups = nominate.unread_report(rep["unread"], props, rules)
        claims = sum(u["claims"] for u in rep["unread"].values())
        say("\n".join(report.unread(groups, len(qids), claims, a.limit, a.all)))
        return 0

    if not NAME.match(a.name):
        raise SystemExit(f"hydra: '{a.name}' cannot name a collection (letters, digits, - and _); use --name")
    if not records:
        raise SystemExit("hydra: none of those items could be read: " + "; ".join(
            f"{why} ({r['count']})" for why, r in rep["left_out"].items()))
    cdir = root / layout.COLLECTIONS_DIR
    there = [f for f in (cdir / f"{a.name}.json", cdir / f"{a.name}.jsonld") if f.is_file()]
    if there and not a.force:
        raise SystemExit(f"hydra: collection '{a.name}' exists; --force replaces it, or --name names another")
    for f in there:
        f.unlink()
    cdir.mkdir(parents=True, exist_ok=True)
    out = cdir / f"{a.name}.json"
    out.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    labels = {pid: p["label"] for pid, p in api.describe(sorted({pid for pid, _ in rep["mapped"]}), _cache(root)).items()}
    say("\n".join(report.imported(out, len(records), len(qids), rep, labels, qids)))
    if not a.no_build:
        from hydra import build
        say("")
        say(build.report(root, build.build_archive(root), verb="Rebuilt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
