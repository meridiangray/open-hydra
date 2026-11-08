"""history: snapshots and branches of the archive's authored files.

    hydra-ctl history [<dir>] status
    hydra-ctl history [<dir>] snapshot -m MESSAGE
    hydra-ctl history [<dir>] log [REF] [-n N]
    hydra-ctl history [<dir>] diff [A] [B]          A default HEAD, B default the working files
    hydra-ctl history [<dir>] branch [NAME [--at REF] | --delete NAME]
    hydra-ctl history [<dir>] switch BRANCH | -c NEW
    hydra-ctl history [<dir>] restore REF [PATH ...]
    hydra-ctl history [<dir>] merge REF [--ours | --theirs]
    hydra-ctl history [<dir>] compare A [B]         build both, compare what they produce
    hydra-ctl history [<dir>] tag NAME [REF]
    hydra-ctl history [<dir>] describe [REF]        what a snapshot did, in a reader's terms
    hydra-ctl history [<dir>] squash [SINCE] -m MESSAGE [--until REF] [--author NAME] [--confirm]
    hydra-ctl history [<dir>] relabel --author NAME [--replace OLD] [--confirm]
    hydra-ctl history [<dir>] gc

What is kept: hydra.yaml, collections/, .hydra/ (rules, review, schema, sources,
resources) and universe/; never what a build recomputes (.hydra/parsed/,
universe/.parsed/, the cache). It lives in .hydra/history/, so a `.hydra` file
carries it (`pack --no-history` leaves it out). Commands that write the archive
(save, import, answer, review, reset, stubs, hints, collections, universe
review and publish) take a snapshot after they write, marked `auto`; a
snapshot with nothing changed is not taken. REF is a branch, a tag, a snapshot
id or its first characters, HEAD or HEAD~N. Restore and merge add a snapshot
on top. `squash` is the one rewrite, asked for by name: the snapshots after
SINCE (default: all of the branch) become one change with MESSAGE, and the
squashed ones are deleted with their authors; it previews unless --confirm.
A snapshot's author is $HYDRA_AUTHOR, else hydra.yaml `author:`, else the
system user. `history: off` in hydra.yaml turns the automatic snapshots off."""
from __future__ import annotations

import argparse
import json

from hydra import history as H
from hydra import resources
from hydra.cli import style


def _ap() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="hydra-ctl history", description="Snapshots and branches of the authored files.")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("snapshot"); s.add_argument("-m", "--message", required=True)
    s = sub.add_parser("log"); s.add_argument("ref", nargs="?"); s.add_argument("-n", type=int, default=30)
    s = sub.add_parser("diff"); s.add_argument("a", nargs="?", default="HEAD"); s.add_argument("b", nargs="?")
    s = sub.add_parser("branch"); s.add_argument("name", nargs="?"); s.add_argument("--at")
    s.add_argument("--delete", metavar="NAME")
    s = sub.add_parser("switch"); s.add_argument("branch", nargs="?"); s.add_argument("-c", dest="create", metavar="NEW")
    s = sub.add_parser("restore"); s.add_argument("ref"); s.add_argument("paths", nargs="*")
    s = sub.add_parser("merge"); s.add_argument("ref")
    g = s.add_mutually_exclusive_group(); g.add_argument("--ours", action="store_true"); g.add_argument("--theirs", action="store_true")
    s = sub.add_parser("compare"); s.add_argument("a"); s.add_argument("b", nargs="?")
    s = sub.add_parser("tag"); s.add_argument("name"); s.add_argument("ref", nargs="?")
    s = sub.add_parser("describe"); s.add_argument("ref", nargs="?", default="HEAD")
    s = sub.add_parser("squash"); s.add_argument("since", nargs="?"); s.add_argument("-m", "--message", required=True)
    s.add_argument("--until"); s.add_argument("--author"); s.add_argument("--confirm", action="store_true")
    s = sub.add_parser("relabel"); s.add_argument("--author", required=True); s.add_argument("--replace")
    s.add_argument("--confirm", action="store_true")
    sub.add_parser("gc")
    return ap


def _split(argv):
    """The archive may come first: `history <dir> log`."""
    argv = list(argv or [])
    if argv and resources.names_archive(argv[0]) and argv[0] not in _SUBS:
        return argv[0], argv[1:]
    return None, argv


_SUBS = {"status", "snapshot", "log", "diff", "branch", "switch", "restore", "merge", "compare", "tag", "gc",
         "describe", "squash", "relabel"}


def _count(d: dict, what: str) -> str:
    return ", ".join(f"{len(v)} {k}" for k, v in d.items() if v) + f" {what}" if any(d.values()) else ""


def main(argv: list[str] | None = None, say=print) -> int:
    where, rest = _split(argv)
    a = _ap().parse_args(rest)
    root = resources.archive(where)
    js = a.format == "json"
    out = lambda obj: say(json.dumps(obj, indent=1, ensure_ascii=False))

    if a.cmd == "status":
        s = H.status(root)
        if js:
            return out(s) or 0
        say(f"on {style.name(s['branch'] or 'no branch (detached)')}, at "
            f"{s['head'][:12] if s['head'] else 'no snapshot yet'}")
        for kind in ("added", "removed", "modified"):
            for p in s[kind]:
                say(f"  {kind:9} {p}")
        if not (s["added"] or s["removed"] or s["modified"]):
            say(style.aside("  no changes since the last snapshot"))
    elif a.cmd == "snapshot":
        sid = H.snapshot(root, a.message)
        say(f"{style.verb('Snapshot')} {sid[:12]}" if sid else "nothing changed since the last snapshot")
    elif a.cmd == "log":
        rows = H.log(root, a.ref, a.n)
        if js:
            return out([{k: v for k, v in r.items() if k != "files"} for r in rows]) or 0
        for r in rows:
            mark = style.aside(" (auto)") if r.get("auto") else ""
            merge = style.aside(f" merge of {', '.join(p[:8] for p in r['parents'])}") if len(r["parents"]) > 1 else ""
            say(f"{style.accent(r['id'][:12])} {r['time']} {r['author']}: {r['message']}{mark}{merge}")
        if not rows:
            say("no snapshots yet")
    elif a.cmd == "diff":
        rows = H.diff(root, a.a, a.b)
        if js:
            return out(rows) or 0
        for r in rows:
            detail = next((_count(r[k], k.rstrip("s") if k != "hs" else "H") for k in ("records", "decisions", "hs")
                           if k in r), "")
            say(f"  {r['change']:9} {r['path']}" + (style.aside(f"  {detail}") if detail else ""))
        if not rows:
            say("no difference")
    elif a.cmd == "branch":
        if a.delete:
            H.delete_branch(root, a.delete)
            say(f"{style.verb('Deleted')} branch {a.delete}")
        elif a.name:
            sid = H.create_branch(root, a.name, a.at)
            say(f"{style.verb('Branch')} {a.name} at {sid[:12]} " + style.aside(f"(switch to it: history switch {a.name})"))
        else:
            cur = H.head(root)[0]
            for name, sid in H.branches(root).items():
                say(f"{'*' if name == cur else ' '} {name:24} {sid[:12]}")
            for name, sid in H.tags(root).items():
                say(f"  {name:24} {sid[:12]} " + style.aside("tag"))
    elif a.cmd == "switch":
        if a.create:
            H.switch(root, a.create, create=True)
            say(f"{style.verb('Switched')} to new branch {a.create}")
        elif a.branch:
            changed = H.switch(root, a.branch)
            say(f"{style.verb('Switched')} to {a.branch}: {style.plural(len(changed), 'file')} changed"
                + (style.aside("; rebuild to see it") if changed else ""))
        else:
            raise SystemExit("hydra: history switch BRANCH, or -c NEW")
    elif a.cmd == "restore":
        changed, sid = H.restore(root, a.ref, a.paths)
        say(f"{style.verb('Restored')} {style.plural(len(changed), 'file')} from {a.ref}"
            + (f"; snapshot {sid[:12]}; rebuild to see it" if sid else " (already equal)"))
    elif a.cmd == "merge":
        res = H.merge(root, a.ref, prefer="ours" if a.ours else "theirs" if a.theirs else None)
        if js:
            return out(res) or (0 if res.get("merged") or res.get("reason") == "already contained" else 1)
        if res.get("merged"):
            say(f"{style.verb('Merged')} {a.ref}: {style.plural(len(res['changed']), 'file')} changed, "
                f"snapshot {res['snapshot'][:12]}; rebuild to see it")
            for p, keys in res["settled"].items():
                say(style.aside(f"  {p}: {len(keys)} clash(es) settled ({', '.join(map(str, keys[:5]))})"))
        elif res.get("reason") == "already contained":
            say(f"{a.ref} is already part of this branch")
        else:
            say(f"not merged: {res['reason']}")
            for p, what in res["conflicts"].items():
                say(f"  {p}: {', '.join(map(str, what[:8]))}")
            return 1
    elif a.cmd == "compare":
        res = H.compare(root, a.a, a.b)
        if js:
            return out(res) or 0
        e, m, q = res["entities"], res["merges"], res["open_questions"]
        say(f"entities {e['before']} -> {e['after']} ({len(e['added'])} new, {len(e['removed'])} gone, "
            f"{len(e['renamed'])} renamed); merges {len(m['new'])} new, {len(m['undone'])} undone; "
            f"open questions {q['before']} -> {q['after']}")
        for x in e["added"][:15]:
            say(f"  + {x}")
        for x in e["removed"][:15]:
            say(f"  - {x}")
        for x, y in e["renamed"][:10]:
            say(f"  ~ {x} -> {y}")
        for g in m["new"][:10]:
            say(f"  merged: {', '.join(g)}")
    elif a.cmd == "tag":
        sid = H.tag(root, a.name, a.ref)
        say(f"{style.verb('Tagged')} {sid[:12]} {a.name}")
    elif a.cmd == "describe":
        d = H.describe(root, H.resolve(root, a.ref))
        if js:
            return out(d) or 0
        say(f"{style.accent(d['sid'][:12])} {d['time']} {d['author']}" + (f": {d['message']}" if d["message"] else ""))
        say(f"  {d['headline']}")
    elif a.cmd == "squash":
        res = H.squash(root, a.since, a.message, a.author, until=a.until, confirm=a.confirm)
        if js:
            return out(res) or 0
        say(f"{res['snapshots']} snapshots ({res['first']} to {res['last']}; by {', '.join(res['authors'])}) "
            f"{'became' if a.confirm else 'would become'} one: \"{res['message']}\" by {res['author']}")
        for c in res["changes"]["collections"]:
            say(style.aside(f"  {c['name']}: +{c['added']} ~{c['changed']} -{c['removed']}"))
        if a.confirm:
            say(f"{style.verb('Squashed')} into {res['squashed_into'][:12]}; {res['freed']['removed']} unused stored files removed")
        else:
            say(style.aside("  preview only: add --confirm to squash"))
    elif a.cmd == "relabel":
        res = H.relabel(root, a.author, a.replace, confirm=a.confirm)
        if js:
            return out(res) or 0
        say(f"{res['relabelled']} of {res['snapshots']} snapshots {'were' if a.confirm else 'would be'} relabelled: "
            f"authors {', '.join(res['authors_now'])} -> {', '.join(res['authors_after'])}")
        if not a.confirm and res["relabelled"]:
            say(style.aside("  preview only: add --confirm to rewrite"))
    elif a.cmd == "gc":
        res = H.gc(root)
        say(f"{style.verb('Removed')} {style.plural(res['removed'], 'unused stored file')}; {res['kept']} kept")
    return 0
