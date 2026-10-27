"""pack / unpack: an archive as one portable `.hydra` file (a zip).

    hydra-ctl pack [<dir>] [-o FILE.hydra] [--no-parsed] [--force]
    hydra-ctl unpack FILE.hydra [<dir>]

`pack` stores everything the archive is made of: `hydra.yaml`, `collections/`,
`session/`, and `.hydra/` (sources, rules with your decisions, schema,
resources, and the last build in `.hydra/parsed/`), so the pack can be read at once. `--no-parsed`
leaves the build out for a smaller file; a build regenerates it byte for byte,
and hydra builds it on the first command that needs it.
Backups (`*.bak`), `__pycache__` and activation markers never go in; neither do
symbolic links. The same archive always packs to the same bytes (sorted entries,
fixed timestamps). `hydra-pack.json` inside lists every file with its SHA-256.
Default output: `<archive name>.hydra` in the current folder; an existing file
is kept unless `--force`.

`unpack` writes into `<dir>` (default: a folder named after the file, beside
it), which must be new or empty; `init FILE.hydra` does the same. It refuses a pack whose paths leave that folder, one with
no `hydra.yaml`, and any file whose SHA-256 differs from `hydra-pack.json`;
nothing is left behind when it refuses."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import yaml

from hydra import layout, resources
from hydra.cli import style

PACK_INDEX = "hydra-pack.json"
PACK_FORMAT = 1
SUFFIX = ".hydra"
_EPOCH = (1980, 1, 1, 0, 0, 0)                 # zip's earliest date: packs do not depend on mtimes
_SKIP_DIRS = {"__pycache__"}
_SKIP_FILES = re.compile(r"(\.bak$|^\.hydra-activate$|^\.DS_Store$)")


def _files(root: Path, with_parsed: bool) -> tuple[list[str], list[str]]:
    """-> (archive-relative posix paths to pack, sorted; symbolic links skipped)."""
    out, links = [], []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        parts = rel.parts
        if any(x in _SKIP_DIRS for x in parts) or rel.as_posix().startswith(f"{layout.INTERNAL}/cache/") \
                or (not with_parsed and rel.as_posix().startswith(layout.PARSED_DIR + "/")):
            continue
        if p.is_symlink():
            links.append(rel.as_posix())
            continue
        if p.is_file() and not _SKIP_FILES.search(p.name):
            out.append(rel.as_posix())
    return out, links


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _name(root: Path) -> str:
    m = root / layout.MANIFEST
    doc = (yaml.safe_load(m.read_text(encoding="utf-8")) or {}) if m.is_file() else {}
    return str(doc.get("name") or root.resolve().name)


def pack(root, out=None, with_parsed: bool = True, force: bool = False) -> tuple[Path, int, list[str]]:
    """-> (the .hydra written, files packed, symbolic links skipped)."""
    root = Path(root)
    if not resources.is_archive(root):
        raise SystemExit(f"hydra: {root} is not an archive (no {layout.MANIFEST})")
    name = _name(root)
    out = Path(out) if out else Path.cwd() / (re.sub(r"[^\w.-]+", "-", name).strip("-.") + SUFFIX)
    if out.suffix != SUFFIX:
        out = out.with_name(out.name + SUFFIX)
    if out.exists() and not force:
        raise SystemExit(f"hydra: {out} exists; --force replaces it")
    out_abs = out.resolve()
    with_parsed = with_parsed and (root / layout.BUILD_YAML).is_file()     # never built: nothing to carry
    files, links = _files(root, with_parsed)
    files = [f for f in files if (root / f).resolve() != out_abs]       # never pack the pack itself
    index = {"format": PACK_FORMAT, "name": name, "parsed": with_parsed, "files": {}}
    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            data = (root / rel).read_bytes()
            index["files"][rel] = _sha(data)
            info = zipfile.ZipInfo(rel, date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        info = zipfile.ZipInfo(PACK_INDEX, date_time=_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    tmp.replace(out)
    return out, len(files), links


def _safe(rel: str) -> bool:
    p = PurePosixPath(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts and "\\" not in rel and ":" not in p.parts[0]


def unpack(pack_file, dest=None) -> tuple[Path, dict]:
    """-> (the archive folder written, the pack's index)."""
    src = Path(pack_file)
    if not src.is_file():
        raise SystemExit(f"hydra: {src} not found")
    dest = Path(dest) if dest else src.parent / (src.name[:-len(SUFFIX)] if src.name.endswith(SUFFIX) else src.stem)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"hydra: {dest} exists and is not empty")
    try:
        z = zipfile.ZipFile(src)
    except zipfile.BadZipFile:
        raise SystemExit(f"hydra: {src} is not a .hydra pack (not a zip)")
    with z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        bad = [n for n in names if not _safe(n)]
        if bad:
            raise SystemExit(f"hydra: {src} has paths outside the archive ({bad[0]}); nothing written")
        if PACK_INDEX not in names:
            raise SystemExit(f"hydra: {src} has no {PACK_INDEX}; not a .hydra pack")
        index = json.loads(z.read(PACK_INDEX))
        if index.get("format") != PACK_FORMAT:
            raise SystemExit(f"hydra: {src} is pack format {index.get('format')}; this hydra reads {PACK_FORMAT}")
        listed = index.get("files") or {}
        if layout.MANIFEST not in listed:
            raise SystemExit(f"hydra: {src} holds no {layout.MANIFEST}; not an archive")
        extra = sorted(set(names) - set(listed) - {PACK_INDEX})
        missing = sorted(set(listed) - set(names))
        if extra or missing:
            raise SystemExit(f"hydra: {src} does not match its {PACK_INDEX} "
                             f"({'unlisted ' + extra[0] if extra else 'missing ' + missing[0]}); nothing written")
        created = not dest.exists()
        try:
            for rel in sorted(listed):
                data = z.read(rel)
                if _sha(data) != listed[rel]:
                    raise SystemExit(f"hydra: {rel} in {src} is damaged (checksum differs); nothing written")
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (dest / layout.PARSED_DIR).mkdir(exist_ok=True)
        except BaseException:
            if created:
                shutil.rmtree(dest, ignore_errors=True)
            else:                                   # it was an empty folder: empty it again
                for child in dest.iterdir():
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            raise
    return dest, index


def main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl pack", description="Pack an archive into one .hydra file.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    ap.add_argument("-o", "--out", help="the .hydra to write (default: <archive name>.hydra here)")
    ap.add_argument("--no-parsed", action="store_true", help="leave out .hydra/parsed/ (the last build)")
    ap.add_argument("--force", action="store_true", help="replace an existing file")
    a = ap.parse_args(argv)
    root = resources.archive(a.dir)
    built = (root / layout.BUILD_YAML).is_file()
    out, n, links = pack(root, a.out, not a.no_parsed, a.force)
    say(f"{style.verb('Packed')} {style.name(root.name)} into {style.path(out)}")
    for line in style.across(["size", "build"], [f"{out.stat().st_size / 1024:,.0f} KB",
                                                 "left out" if a.no_parsed else "included" if built else "never built"]):
        say(line)
    if links:
        say(f"skipped {len(links)} symbolic link(s): {', '.join(links[:3])}{' …' if len(links) > 3 else ''}")
    return 0


def unpack_main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl unpack", description="Unpack a .hydra file into an archive.")
    ap.add_argument("file")
    ap.add_argument("dir", nargs="?", help="where to unpack (default: the file's name, here); new or empty")
    a = ap.parse_args(argv)
    dest, index = unpack(a.file, a.dir)
    say(f"{style.verb('Unpacked')} {a.file} into {style.path(dest)}")
    if not index.get("parsed"):
        resources.warn("this pack carries no build (.hydra/parsed/); it builds on the first command that needs it")
    return 0
