"""history.py — snapshots and branches of an archive's authored files.

A snapshot records every file a person or an agent authored, by SHA-256, in
the shape of a pack index; what a build recomputes is never kept, since a
build of the same files gives the same result. Everything lives in
`.hydra/history/`, so it travels inside a `.hydra` file:

    objects/ab/abcdef...     the files, zlib-compressed, stored once per content
    snapshots/<id>.json      {parents, files: {path: sha}, message, author, time, auto}
    refs/heads/<branch>      the snapshot a branch is at
    refs/tags/<tag>          a named snapshot
    HEAD                     "ref: heads/main", or a snapshot id

History is not rewritten behind anyone's back: `restore` and `merge` add snapshots on top. The one
exception is asked for by name: `squash` replaces a branch's latest snapshots with one change (its
message, its author), for a run of working steps that should read as a single change.
`describe` says what a snapshot did in a reader's terms (records added, corrected, removed per
collection; ids made permanent; decisions; settings); the wiki's recent changes and change pages use it.
The unit is the file. `diff` reads inside collections (records by id) and
decision files (decisions by key) only to say what changed; `merge` merges a
collection record by record and the decision files by their own rules.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import shutil
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

from hydra import layout
from hydra.universe import hid, table

TRACKED_TOP = (layout.MANIFEST, "wiki.yaml", layout.COLLECTIONS_DIR, layout.INTERNAL, layout.UNIVERSE_DIR)
UNTRACKED = (layout.PARSED_DIR + "/", layout.CACHE_DIR + "/", layout.HISTORY_DIR + "/",
             layout.UNIVERSE_PARSED + "/",
             layout.FTM_DIR + "/")     # the vendored FtM schema: not authored, pinned by its hash in hydra.yaml
_SKIP_PARTS = {"__pycache__"}
_SKIP_FILES = re.compile(r"(\.bak$|\.part$|^\.hydra-activate$|^\.DS_Store$)")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
DECISION_FILES = re.compile(r"(^|/)(verdicts\.yaml)$")


class HistoryError(SystemExit):
    def __init__(self, msg: str):
        super().__init__(f"hydra: {msg}")


def _h(root) -> Path:
    return Path(root) / layout.HISTORY_DIR


def enabled(root) -> bool:
    m = Path(root) / layout.MANIFEST
    doc = (yaml.safe_load(m.read_text(encoding="utf-8")) or {}) if m.is_file() else {}
    return doc.get("history", True) not in (False, "off")


def tracked(root) -> dict[str, Path]:
    """-> {archive-relative posix path: file}: what a snapshot records."""
    root = Path(root)
    out = {}
    for top in TRACKED_TOP:
        p = root / top
        items = [p] if p.is_file() else sorted(p.rglob("*")) if p.is_dir() else []
        for f in items:
            rel = f.relative_to(root).as_posix()
            if any(x in _SKIP_PARTS for x in f.parts) or rel.startswith(UNTRACKED) or f.is_symlink():
                continue
            if f.is_file() and not _SKIP_FILES.search(f.name):
                out[rel] = f
    return out


# -------------------------------------------------------------------- storage

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _obj(root, sha: str) -> Path:
    return _h(root) / "objects" / sha[:2] / sha


def put(root, data: bytes) -> str:
    sha = _sha(data)
    p = _obj(root, sha)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(zlib.compress(data, 6))
        tmp.replace(p)
    return sha


def get(root, sha: str) -> bytes:
    p = _obj(root, sha)
    if not p.is_file():
        raise HistoryError(f"history object {sha[:12]} is missing")
    data = zlib.decompress(p.read_bytes())
    if _sha(data) != sha:
        raise HistoryError(f"history object {sha[:12]} is damaged")
    return data


def _snap_path(root, sid: str) -> Path:
    return _h(root) / "snapshots" / f"{sid}.json"


def snap(root, sid: str) -> dict:
    p = _snap_path(root, sid)
    if not p.is_file():
        raise HistoryError(f"no snapshot {sid}")
    return {"id": sid, **json.loads(p.read_text(encoding="utf-8"))}


def _all_snaps(root) -> list[str]:
    d = _h(root) / "snapshots"
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


# ----------------------------------------------------------------------- refs

def head(root) -> tuple[str | None, str | None]:
    """-> (branch or None when detached, snapshot id or None before the first snapshot)."""
    p = _h(root) / "HEAD"
    text = p.read_text(encoding="utf-8").strip() if p.is_file() else "ref: heads/main"
    if text.startswith("ref: heads/"):
        branch = text[len("ref: heads/"):]
        return branch, ref_value(root, f"heads/{branch}")
    return None, text or None


def ref_value(root, ref: str) -> str | None:
    p = _h(root) / "refs" / ref
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def _set_ref(root, ref: str, sid: str) -> None:
    p = _h(root) / "refs" / ref
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(sid + "\n", encoding="utf-8")


def _set_head(root, branch: str | None, sid: str | None = None) -> None:
    p = _h(root) / "HEAD"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"ref: heads/{branch}\n" if branch else f"{sid}\n", encoding="utf-8")


def branches(root) -> dict[str, str]:
    d = _h(root) / "refs" / "heads"
    return {p.relative_to(d).as_posix(): p.read_text(encoding="utf-8").strip()
            for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}


def tags(root) -> dict[str, str]:
    d = _h(root) / "refs" / "tags"
    return {p.relative_to(d).as_posix(): p.read_text(encoding="utf-8").strip()
            for p in sorted(d.rglob("*")) if p.is_file()} if d.is_dir() else {}


def resolve(root, ref: str | None) -> str:
    """A branch, tag, snapshot id (or its first characters), `HEAD`, `HEAD~N` -> snapshot id."""
    ref = (ref or "HEAD").strip()
    back = 0
    m = re.match(r"^(.*?)~(\d+)$", ref)
    if m:
        ref, back = m.group(1), int(m.group(2))
    if ref == "HEAD":
        sid = head(root)[1]
    else:
        sid = ref_value(root, f"heads/{ref}") or ref_value(root, f"tags/{ref}")
        if not sid:
            hits = [s for s in _all_snaps(root) if s.startswith(ref)] if len(ref) >= 4 else []
            if len(hits) > 1:
                raise HistoryError(f"'{ref}' names {len(hits)} snapshots; give more characters")
            sid = hits[0] if hits else None
    if not sid:
        raise HistoryError(f"no snapshot, branch or tag '{ref}'" if ref != "HEAD" else "no snapshot yet")
    for _ in range(back):
        parents = snap(root, sid)["parents"]
        if not parents:
            raise HistoryError(f"{ref}~{back} goes past the first snapshot")
        sid = parents[0]
    return sid


# ------------------------------------------------------------------ snapshots

def current_files(root) -> dict[str, str]:
    """-> {path: sha} of the working files, storing any content not stored yet."""
    return {rel: put(root, f.read_bytes()) for rel, f in tracked(root).items()}


def _hash_files(root) -> dict[str, str]:
    return {rel: _sha(f.read_bytes()) for rel, f in tracked(root).items()}


def status(root) -> dict:
    """What changed since HEAD: {added, removed, modified, head, branch}."""
    branch, sid = head(root)
    before = snap(root, sid)["files"] if sid else {}
    now = _hash_files(root)
    return {"branch": branch, "head": sid,
            "added": sorted(set(now) - set(before)), "removed": sorted(set(before) - set(now)),
            "modified": sorted(p for p in now if p in before and now[p] != before[p])}


def dirty(root) -> bool:
    s = status(root)
    return bool(s["added"] or s["removed"] or s["modified"])


def author(root=None) -> str:
    """Who a snapshot says made it: $HYDRA_AUTHOR, else hydra.yaml `author:` (a name, a team, "editors"),
    else the system's user name. Set `author:` to keep a personal name out of an archive others will see."""
    if os.environ.get("HYDRA_AUTHOR"):
        return os.environ["HYDRA_AUTHOR"]
    if root is not None:
        m = Path(root) / layout.MANIFEST
        try:
            doc = (yaml.safe_load(m.read_text(encoding="utf-8")) or {}) if m.is_file() else {}
        except (OSError, yaml.YAMLError):
            doc = {}
        if isinstance(doc, dict) and str(doc.get("author") or "").strip():
            return str(doc["author"]).strip()
    try:
        return getpass.getuser()
    except Exception:                       # no user name on this system
        return "unknown"


def snapshot(root, message: str, *, who: str | None = None, auto: bool = False,
             parents: list[str] | None = None, now: str | None = None, force: bool = False) -> str | None:
    """Record the authored files. -> the new snapshot id, or None when nothing changed
    (and `force` is off). `parents` defaults to HEAD; a merge passes two."""
    root = Path(root)
    branch, sid = head(root)
    files = current_files(root)
    parents = [p for p in (parents if parents is not None else [sid]) if p]
    if not force and parents and snap(root, parents[0])["files"] == files:
        return None
    body = {"parents": parents, "files": dict(sorted(files.items())), "message": message.strip(),
            "author": who or author(root), "auto": auto,
            "time": now or datetime.now(timezone.utc).isoformat(timespec="seconds")}
    text = json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False)
    new = _sha(text.encode("utf-8"))[:16]
    p = _snap_path(root, new)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text + "\n", encoding="utf-8")
    if branch:
        _set_ref(root, f"heads/{branch}", new)
        _set_head(root, branch)
    else:
        _set_head(root, None, new)
    return new


def auto(root, message: str, who: str | None = None) -> str | None:
    """The snapshot a command takes after it writes: never fails the command."""
    try:
        if not enabled(root):
            return None
        return snapshot(root, message, who=who, auto=True)
    except Exception as e:                 # a full disk or a damaged history must not lose the change itself
        from hydra.cli import style
        style.warn(f"history: no snapshot taken ({e})")
        return None


def log(root, ref: str | None = None, limit: int = 50) -> list[dict]:
    """Snapshots from `ref` back, newest first (first parents, then the rest by time)."""
    try:
        start = resolve(root, ref)
    except HistoryError:
        if ref:
            raise
        return []
    seen, out, todo = set(), [], [start]
    while todo and len(out) < limit:
        todo.sort(key=lambda s: snap(root, s)["time"], reverse=True)
        sid = todo.pop(0)
        if sid in seen:
            continue
        seen.add(sid)
        s = snap(root, sid)
        out.append(s)
        todo += [p for p in s["parents"] if p not in seen]
    return out


def ancestors(root, sid: str) -> set[str]:
    seen, todo = set(), [sid]
    while todo:
        s = todo.pop()
        if s not in seen:
            seen.add(s)
            todo += snap(root, s)["parents"]
    return seen


def merge_base(root, a: str, b: str) -> str | None:
    common = ancestors(root, a) & ancestors(root, b)
    if not common:
        return None
    # the common ancestor no other common ancestor descends from
    return max(common, key=lambda s: (len(ancestors(root, s)), snap(root, s)["time"]))


# --------------------------------------------------------------- write files

def _write_files(root, files: dict[str, str], only: list[str] | None = None) -> list[str]:
    """Make the working files equal `files` (or just the paths in `only`). -> paths changed."""
    root = Path(root)
    now = tracked(root)
    targets = set(files) | set(now) if only is None else set(only)
    changed = []
    for rel in sorted(targets):
        if not _safe(rel):
            raise HistoryError(f"refusing path {rel!r}")
        dest = root / rel
        if rel in files:
            data = get(root, files[rel])
            if not dest.is_file() or dest.read_bytes() != data:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                changed.append(rel)
        elif dest.is_file() and rel in now:
            dest.unlink()
            changed.append(rel)
    return changed


def _safe(rel: str) -> bool:
    p = PurePosixPath(rel)
    return not p.is_absolute() and ".." not in p.parts and rel.split("/", 1)[0] in TRACKED_TOP


def switch(root, branch: str, create: bool = False) -> list[str]:
    """Make `branch` current and the working files its snapshot. Refuses unsnapshotted changes."""
    root = Path(root)
    if not REF.match(branch):
        raise HistoryError(f"'{branch}' cannot name a branch")
    cur_branch, cur = head(root)
    if dirty(root):
        raise HistoryError("there are changes since the last snapshot; `history snapshot` them first "
                           "(or `history restore` to drop them)")
    exists = branch in branches(root)
    if create:
        if exists:
            raise HistoryError(f"branch {branch} exists")
        if not cur:
            raise HistoryError("no snapshot yet to branch from; `history snapshot` first")
        _set_ref(root, f"heads/{branch}", cur)
        _set_head(root, branch)
        return []
    if not exists:
        raise HistoryError(f"no branch {branch} (create it with `history branch {branch}`)")
    target = branches(root)[branch]
    changed = _write_files(root, snap(root, target)["files"])
    _set_head(root, branch)
    return changed


def create_branch(root, name: str, at: str | None = None) -> str:
    if not REF.match(name):
        raise HistoryError(f"'{name}' cannot name a branch")
    if name in branches(root):
        raise HistoryError(f"branch {name} exists")
    sid = resolve(root, at)
    _set_ref(root, f"heads/{name}", sid)
    return sid


def delete_branch(root, name: str) -> None:
    if name not in branches(root):
        raise HistoryError(f"no branch {name}")
    if head(root)[0] == name:
        raise HistoryError(f"{name} is the current branch")
    (_h(root) / "refs" / "heads" / name).unlink()


def tag(root, name: str, at: str | None = None) -> str:
    if not REF.match(name):
        raise HistoryError(f"'{name}' cannot name a tag")
    if name in tags(root):
        raise HistoryError(f"tag {name} exists")
    sid = resolve(root, at)
    _set_ref(root, f"tags/{name}", sid)
    return sid


def restore(root, ref: str, paths: list[str] | None = None, message: str = "",
            who: str | None = None) -> tuple[list[str], str | None]:
    """Working files (or `paths`, files or folders) back to `ref`, then a snapshot of the result."""
    sid = resolve(root, ref)
    files = snap(root, sid)["files"]
    only = None
    if paths:
        now = tracked(root)
        wanted = [p.strip("/").replace("\\", "/") for p in paths]
        only = [r for r in set(files) | set(now) if any(r == w or r.startswith(w + "/") for w in wanted)]
        if not only:
            raise HistoryError(f"no file under {', '.join(wanted)} in {sid} or the archive")
    changed = _write_files(root, files, only)
    new = snapshot(root, message or f"restore {', '.join(paths) if paths else 'all files'} from {sid[:12]}",
                   who=who) if changed else None
    return changed, new


# ------------------------------------------------------------------ reading

def _records(data: bytes) -> dict[str, dict] | None:
    """A collection's records by id: a JSON array (as `save` writes) or one record per line (as `import`)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        doc = json.loads(text) if text.strip() else []
    except ValueError:
        try:
            doc = [json.loads(l) for l in text.splitlines() if l.strip()]
        except ValueError:
            return None
    if isinstance(doc, list) and all(isinstance(r, dict) and r.get("id") for r in doc):
        return {str(r["id"]): r for r in doc}
    return None


def _decisions(data: bytes) -> dict | None:
    try:
        doc = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _canon_rows(data: bytes) -> dict[str, dict] | None:
    try:
        rows = [json.loads(l) for l in data.decode("utf-8").splitlines() if l.strip()]
    except (ValueError, UnicodeDecodeError):
        return None
    return {r["h"].rsplit("-", 1)[-1]: r for r in rows if isinstance(r, dict) and r.get("h")}


def _kind(rel: str) -> str:
    if rel.startswith(layout.COLLECTIONS_DIR + "/") and rel.endswith(".json") and rel != layout.COLLECTIONS_MANIFEST:
        return "collection"
    if rel.startswith(layout.SOURCE_ENTRIES + "/") and rel.endswith(".json"):
        return "collection"
    if DECISION_FILES.search(rel):
        return "decisions"
    if rel == layout.CANON:
        return "canon"
    return "file"


def _summary(kind: str, a: bytes | None, b: bytes | None) -> dict:
    """What changed inside one file, in its own terms."""
    if kind == "collection":
        ra, rb = _records(a or b"[]"), _records(b or b"[]")
        if ra is not None and rb is not None:
            return {"records": {"added": sorted(set(rb) - set(ra)), "removed": sorted(set(ra) - set(rb)),
                                "changed": sorted(k for k in rb if k in ra and rb[k] != ra[k])}}
    if kind == "decisions":
        da, db = _decisions(a or b"{}") or {}, _decisions(b or b"{}") or {}
        return {"decisions": {"added": sorted(set(db) - set(da)), "removed": sorted(set(da) - set(db)),
                              "changed": sorted(k for k in db if k in da and db[k] != da[k])}}
    if kind == "canon":
        ca, cb = _canon_rows(a or b"") or {}, _canon_rows(b or b"") or {}
        return {"hs": {"added": sorted(set(cb) - set(ca)), "removed": sorted(set(ca) - set(cb)),
                       "changed": sorted(k for k in cb if k in ca and cb[k] != ca[k])}}
    return {}


def diff(root, a: str | None, b: str | None = None) -> list[dict]:
    """Files that differ between snapshot `a` and `b` (default: the working files)."""
    fa = snap(root, resolve(root, a))["files"]
    fb = snap(root, resolve(root, b))["files"] if b else current_files(root)
    return _diff_files(root, fa, fb)


def _diff_files(root, fa: dict, fb: dict) -> list[dict]:
    out = []
    for rel in sorted(set(fa) | set(fb)):
        if fa.get(rel) == fb.get(rel):
            continue
        change = "added" if rel not in fa else "removed" if rel not in fb else "modified"
        da = get(root, fa[rel]) if rel in fa else None
        db = get(root, fb[rel]) if rel in fb else None
        out.append({"path": rel, "change": change, **_summary(_kind(rel), da, db)})
    return out


def _collection_name(rel: str) -> str:
    """A collection's file as a reader names it: collections/assets-bloodstock-estates.json -> "assets-bloodstock-estates"."""
    return PurePosixPath(rel).stem


def records_at(root, sid: str | None, rel: str) -> dict[str, dict]:
    """A collection's records by id as snapshot `sid` holds them ({} when it holds no such file)."""
    if not sid:
        return {}
    sha = snap(root, sid)["files"].get(rel)
    return (_records(get(root, sha)) or {}) if sha else {}


def describe(root, sid: str) -> dict:
    """What one snapshot did, in a reader's terms: {sid, time, author, message, headline, parts,
    collections: [{name, added, changed, removed}] (record ids), published, decisions, settings}."""
    s = snap(root, sid)
    fa = snap(root, s["parents"][0])["files"] if s["parents"] else {}
    changes = _diff_files(root, fa, s["files"])
    cols, published, decided, settings, sources = [], [], [], [], 0
    for c in changes:
        rel = c["path"]
        if "records" in c and rel.startswith(layout.SOURCE_ENTRIES + "/"):
            sources += len(c["records"]["added"])
        elif "records" in c:
            r = c["records"]
            if r["added"] or r["changed"] or r["removed"]:
                cols.append({"name": _collection_name(rel), "path": rel, **r})
        elif "hs" in c:
            published += c["hs"]["added"] + c["hs"]["changed"]
        elif "decisions" in c:
            d = c["decisions"]
            decided += d["added"] + d["changed"] + d["removed"]
        elif rel.startswith(layout.RULES_DIR + "/") or rel in (layout.MANIFEST, "wiki.yaml"):
            settings.append(PurePosixPath(rel).name)
    plural = lambda n, w: f"{n:,} {w}{'' if n == 1 else 's'}"
    parts = []

    def counts(a, c, r) -> str:
        return ", ".join(b for b in (f"added {plural(a, 'record')}" if a else "",
                                     f"corrected {plural(c, 'record')}" if c else "",
                                     f"removed {plural(r, 'record')}" if r else "") if b)
    if len(cols) > 3:                              # many collections: one line of totals, the detail on the change's page
        parts.append(counts(*(sum(len(c[k]) for c in cols) for k in ("added", "changed", "removed")))
                     + f" across {len(cols)} collections")
    for c in cols if len(cols) <= 3 else ():
        parts.append(f"{counts(len(c['added']), len(c['changed']), len(c['removed']))} in {c['name']}")
    if published:
        parts.append(f"made {plural(len(published), 'id')} permanent")
    if decided:
        parts.append(f"recorded {plural(len(decided), 'review decision')}")
    if sources:
        parts.append(f"kept {plural(sources, 'source')}")
    if settings:
        parts.append(f"changed {', '.join(sorted(set(settings)))}")
    head_ = (parts[0][0].upper() + parts[0][1:] + (f"; {'; '.join(parts[1:])}" if len(parts) > 1 else "")) if parts \
        else "No change to the records"
    msg = "" if s.get("auto") else s.get("message", "")
    return {"sid": sid, "time": s["time"], "author": s.get("author", ""), "message": msg, "headline": head_,
            "parts": parts, "collections": cols, "published": published, "decisions": decided,
            "settings": sorted(set(settings)), "squashed": s.get("squashed", 0)}


_PATH = re.compile(r"""(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|tmp|var|mnt)/)[^\s'"]*""")


def plain_command(text: str) -> str:
    """A command line as a snapshot message keeps it: absolute paths (which carry user names) cut to their
    file name: `hydra-ctl import C:/Users/x/.../batch.jsonl` -> `hydra-ctl import batch.jsonl`."""
    return _PATH.sub(lambda m: PurePosixPath(m.group(0).replace("\\", "/")).name or "…", text)


def _line(root) -> tuple[str, list[str]]:
    """The current branch and its snapshots, oldest first; refused on a merge (only a straight line is rewritten)."""
    branch, top = head(root)
    if not branch or not top:
        raise HistoryError("this works on a branch with snapshots; switch to one first")
    if dirty(root):
        raise HistoryError("some changes are not in a snapshot yet: take one (`history snapshot`) first")
    chain, cur = [], top
    while cur:
        s = snap(root, cur)
        if len(s["parents"]) > 1:
            raise HistoryError(f"{cur[:12]} is a merge; history with merges is not rewritten")
        chain.append(cur)
        cur = s["parents"][0] if s["parents"] else None
    return branch, chain[::-1]


def _guard(root, branch: str, old: set[str]) -> None:
    users = [f"branch {b}" for b, s in branches(root).items() if b != branch and ancestors(root, s) & old]
    users += [f"tag {t}" for t, s in tags(root).items() if s in old]
    if users:
        raise HistoryError(f"{', '.join(users)} depend on snapshots this would rewrite")


def _write_snap(root, body: dict) -> str:
    text = json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False)
    new = _sha(text.encode("utf-8"))[:16]
    p = _snap_path(root, new)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text + "\n", encoding="utf-8")
    return new


def _replay(root, parent: str | None, rest: list[str], change=lambda s: s) -> list[str]:
    """Write `rest` (oldest first) again on top of `parent`, each through `change`; -> the new ids.
    The files of each are unchanged; only parents (and what `change` alters) differ, so ids do (a
    snapshot nothing changes keeps its id)."""
    out = []
    for sid in rest:
        s = {k: v for k, v in snap(root, sid).items() if k != "id"}
        parent = _write_snap(root, change({**s, "parents": [parent] if parent else []}))
        out.append(parent)
    return out


def _finish(root, branch: str, new: list[str], old: list[str]) -> dict:
    """Point the branch at the last of `new`; delete the `old` snapshots the new line no longer holds."""
    _set_ref(root, f"heads/{branch}", new[-1])
    _set_head(root, branch)
    keep = set(new)
    for x in old:
        if x not in keep:
            _snap_path(root, x).unlink(missing_ok=True)
    return gc(root)


def squash(root, since: str | None, message: str, who: str | None = None, *, until: str | None = None,
           confirm: bool = False) -> dict:
    """Make the snapshots after `since` up to `until` (default HEAD) one snapshot with `message` and `who`
    as its author: the change as a reader should see it. `since` None starts at the branch's first
    snapshot. Snapshots after `until` are written again on top, unchanged but for their ids. The working
    files are untouched; the old snapshots are deleted (with stored contents only they used), so their
    messages and authors leave the archive. Refused across a merge, or when another branch or a tag
    depends on a snapshot it rewrites. Without `confirm`: a preview."""
    root = Path(root)
    branch, line = _line(root)
    base = resolve(root, since) if since else None
    end = resolve(root, until) if until else line[-1]
    if (base and base not in line) or end not in line:
        raise HistoryError("`since` and `until` must be snapshots of this branch")
    i0, i1 = (line.index(base) + 1 if base else 0), line.index(end)
    group, rest = line[i0:i1 + 1], line[i1 + 1:]
    if not group:
        raise HistoryError("nothing to squash between `since` and `until`")
    _guard(root, branch, set(group) | set(rest))
    snaps = [snap(root, x) for x in group]
    preview = {"snapshots": len(group), "from": group[0][:12], "to": group[-1][:12],
               "first": snaps[0]["time"], "last": snaps[-1]["time"], "rewritten_after": len(rest),
               "authors": sorted({x.get("author", "") for x in snaps}), "message": message.strip(),
               "author": who or author(root), "changes": describe_range(root, base, end)}
    if not confirm:
        return {**preview, "next": "call again with confirm to replace these snapshots with one"}
    new = _write_snap(root, {"parents": [base] if base else [], "files": snaps[-1]["files"],
                             "message": message.strip(), "author": who or author(root), "auto": False,
                             "time": snaps[-1]["time"], "squashed": len(group)})
    line_new = [new] + _replay(root, new, rest)
    freed = _finish(root, branch, line_new, group + rest)
    return {**preview, "squashed_into": new, "tip": line_new[-1], "freed": freed}


def relabel(root, name: str, replace: str | None = None, *, confirm: bool = False) -> dict:
    """Write every snapshot of the current branch again with `name` as its author, where its author is
    `replace` (default: every author that is a person: not an `agent:` one), and with the absolute paths
    in automatic messages cut to file names (they carry user names too). For an archive to be shared
    without the personal names its working snapshots carried. Without `confirm`: a preview."""
    root = Path(root)
    branch, line = _line(root)
    hit = lambda a: (a == replace) if replace else not str(a).startswith("agent:")

    def change(s):
        s = {**s, "author": name} if hit(s.get("author", "")) else s
        return {**s, "message": plain_command(s.get("message", ""))} if s.get("auto") else s
    authors = sorted({snap(root, x).get("author", "") for x in line})
    touched = [x for x in line if change(snap(root, x)) != snap(root, x)]
    preview = {"snapshots": len(line), "relabelled": len(touched), "authors_now": authors,
               "authors_after": sorted({name if hit(a) else a for a in authors})}
    if not confirm or not touched:
        return {**preview, **({"next": "call again with confirm to rewrite the authors"} if touched else {})}
    _guard(root, branch, set(line))
    new = _replay(root, None, line, change)
    freed = _finish(root, branch, new, line)
    return {**preview, "tip": new[-1], "freed": freed}


def describe_range(root, a: str | None, b: str) -> dict:
    """What changed between snapshot `a` (None: nothing) and `b`, as `describe` puts one snapshot."""
    fa = snap(root, a)["files"] if a else {}
    out = {"collections": [], "published": 0}
    for c in _diff_files(root, fa, snap(root, b)["files"]):
        if "records" in c and not c["path"].startswith(layout.SOURCE_ENTRIES + "/"):
            r = c["records"]
            out["collections"].append({"name": _collection_name(c["path"]), "added": len(r["added"]),
                                       "changed": len(r["changed"]), "removed": len(r["removed"])})
        elif "hs" in c:
            out["published"] += len(c["hs"]["added"]) + len(c["hs"]["changed"])
    return out


# -------------------------------------------------------------------- merge

def _merge_records(base, ours, theirs) -> tuple[bytes | None, list[str]]:
    rb, ro, rt = (_records(x) if x is not None else {} for x in (base, ours, theirs))
    if None in (rb, ro, rt):
        return None, ["not a list of records"]
    out, conflicts = {}, []
    for k in sorted(set(rb) | set(ro) | set(rt), key=lambda k: (k not in ro, k)):
        b, o, t = rb.get(k), ro.get(k), rt.get(k)
        if o == t:
            got = o
        elif o == b:
            got = t
        elif t == b:
            got = o
        else:
            conflicts.append(k)
            got = o
        if got is not None:
            out[k] = got
    order = [k for k in ro if k in out] + [k for k in rt if k in out and k not in ro]
    return (json.dumps([out[k] for k in order], indent=1, ensure_ascii=False) + "\n").encode("utf-8"), conflicts


def _merge_decisions(base, ours, theirs) -> tuple[bytes, list[str]]:
    """Three-way by key; both sides changed one key differently: the safe answer, as `verdicts.load`
    does for two files (a merge pair becomes rejected, a pin is dropped)."""
    db, do, dt = (_decisions(x or b"{}") or {} for x in (base, ours, theirs))
    out, conflicts = {}, []
    for k in sorted(set(db) | set(do) | set(dt), key=str):
        b, o, t = db.get(k), do.get(k), dt.get(k)
        if o == t:
            got = o
        elif o == b:
            got = t
        elif t == b:
            got = o
        else:
            conflicts.append(str(k))
            from hydra.review.verdicts import PIN_PREFIXES
            got = None if str(k).startswith(PIN_PREFIXES) else "rejected"
        if got is not None:
            out[k] = got
    return yaml.safe_dump(out, sort_keys=True, allow_unicode=True).encode("utf-8"), conflicts


def _merge_canon(base, ours, theirs) -> tuple[bytes, list[str]]:
    """H-table rows: a state only moves forward, `not` lists join, members of the more decided
    row win; two different redirects of one H are a conflict (ours is kept)."""
    cb, co, ct = (_canon_rows(x or b"") or {} for x in (base, ours, theirs))
    out, conflicts = {}, []
    for k in sorted(set(cb) | set(co) | set(ct)):
        o, t = co.get(k), ct.get(k)
        if o is None or t is None:
            got = o or t
            if cb.get(k) is not None and (o is None) != (t is None) and (o or t) == cb.get(k):
                got = None                          # removed on one side, untouched on the other
        else:
            so, st = (hid.parse(o["h"])[0] or "p"), (hid.parse(t["h"])[0] or "p")
            got = dict(o if table.RANK[so] >= table.RANK[st] else t)
            got["not"] = sorted(set(o.get("not") or []) | set(t.get("not") or [])) or None
            if o.get("redirect") and t.get("redirect") and o["redirect"] != t["redirect"]:
                conflicts.append(k)
                got["redirect"] = o["redirect"]
            else:
                got["redirect"] = o.get("redirect") or t.get("redirect")
            got = {x: v for x, v in got.items() if v is not None}
        if got is not None:
            out[k] = got
    rows = sorted(out.values(), key=lambda r: (r.get("seq", 0), r["h"]))
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"), conflicts


def _merge_file(root, rel: str, b, o, t, prefer: str | None) -> tuple[str | None, list[str]]:
    """One file changed on both sides -> (sha of the result or None for deleted, what clashed).
    Each merger keeps its first side on a clash, so `prefer=theirs` runs it with the sides swapped."""
    data = lambda s: get(root, s) if s else None
    kind = _kind(rel)
    first, second = (t, o) if prefer == "theirs" else (o, t)
    if kind == "collection" and o and t:
        merged, clash = _merge_records(data(b), data(first), data(second))
    elif kind == "decisions":
        merged, clash = _merge_decisions(data(b), data(o), data(t))
        return put(root, merged), clash       # settled by the safe-answer rule: reported, never a stop
    elif kind == "canon":
        merged, clash = _merge_canon(data(b), data(first), data(second))
    else:
        return first, ["changed on both sides"]
    if merged is None:
        return first, clash
    return put(root, merged), clash


def merge(root, other: str, *, prefer: str | None = None, message: str = "") -> dict:
    """Merge snapshot/branch `other` into the current branch. Files changed on one side
    only are taken from that side; a collection merges record by record, decision files
    and the H-table by their own rules. A record (or file) changed differently on both
    sides is a conflict: nothing is written unless `prefer` ("ours" | "theirs") settles it."""
    root = Path(root)
    branch, cur = head(root)
    if not cur:
        raise HistoryError("no snapshot yet to merge into")
    if dirty(root):
        raise HistoryError("there are changes since the last snapshot; `history snapshot` them first")
    them = resolve(root, other)
    if them in ancestors(root, cur):
        return {"merged": False, "reason": "already contained", "changed": []}
    base = merge_base(root, cur, them)
    fb = snap(root, base)["files"] if base else {}
    fo, ft = snap(root, cur)["files"], snap(root, them)["files"]
    result, conflicts, notes = {}, {}, {}
    for rel in sorted(set(fb) | set(fo) | set(ft)):
        b, o, t = fb.get(rel), fo.get(rel), ft.get(rel)
        if o == t:
            got = o
        elif o == b:
            got = t
        elif t == b:
            got = o
        else:
            got, clash = _merge_file(root, rel, b, o, t, prefer)
            if clash and not prefer and _kind(rel) != "decisions":
                conflicts[rel] = clash
                continue
            if clash:
                notes[rel] = clash
        if got:
            result[rel] = got
    if conflicts:
        return {"merged": False, "conflicts": conflicts, "base": base,
                "reason": "conflicts: settle them with --ours or --theirs, or edit and merge again"}
    changed = _write_files(root, result)
    sid = snapshot(root, message or f"merge {other} into {branch or cur[:12]}", parents=[cur, them], force=True)
    return {"merged": True, "snapshot": sid, "changed": changed, "settled": notes, "base": base}


# ------------------------------------------------------------- compare, gc

def checkout_to(root, ref: str, dest) -> Path:
    """Write snapshot `ref` as a plain archive folder at `dest` (for building it aside)."""
    files = snap(root, resolve(root, ref))["files"]
    dest = Path(dest)
    for rel, sha in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(get(root, sha))
    return dest


def compare(root, a: str, b: str | None = None) -> dict:
    """Build both sides in memory and compare what they produce: entities, merges, open questions."""
    from hydra.cli import export as hexport
    from hydra.review import ids

    def compiled(ref):
        with tempfile.TemporaryDirectory(prefix="hydra-compare-") as tmp:
            where = Path(root) if ref is None else checkout_to(root, ref, Path(tmp) / "a")
            cap = hexport.compile_(where)
            r = cap["resolved"]
            groups = {}
            for rec in r.records:
                groups.setdefault(ids.survivor(r.survivors, rec["id"]), set()).add(rec["id"])
            ents = {s: r.cap.get(s, s) for s in r.ents}
            merged = {frozenset(g) for g in groups.values() if len(g) > 1}
            open_ = sum(1 for row in cap["ledger"] if row.get("status") in ("proposed", "unresolved", "conflict"))
            return ents, merged, open_

    ea, ma, qa = compiled(a)
    eb, mb, qb = compiled(b)
    return {"entities": {"before": len(ea), "after": len(eb),
                         "added": sorted(eb[k] for k in set(eb) - set(ea)),
                         "removed": sorted(ea[k] for k in set(ea) - set(eb)),
                         "renamed": sorted((ea[k], eb[k]) for k in set(ea) & set(eb) if ea[k] != eb[k])},
            "merges": {"new": sorted(sorted(g) for g in mb - ma), "undone": sorted(sorted(g) for g in ma - mb)},
            "open_questions": {"before": qa, "after": qb}}


def gc(root) -> dict:
    """Delete stored files no snapshot refers to."""
    keep = set()
    for sid in _all_snaps(root):
        keep.update(snap(root, sid)["files"].values())
    removed = 0
    d = _h(root) / "objects"
    for p in d.rglob("*") if d.is_dir() else []:
        if p.is_file() and p.name not in keep:
            p.unlink()
            removed += 1
    return {"kept": len(keep), "removed": removed}


def init_from(root, src: Path) -> None:
    """Copy another archive's history (`init FILE.hydra` keeps the pack's history)."""
    s = Path(src) / layout.HISTORY_DIR
    if s.is_dir():
        shutil.copytree(s, _h(root), dirs_exist_ok=True)
