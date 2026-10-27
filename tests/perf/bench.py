"""Benchmark and equivalence check (not part of the normal test run).

    # build a set of archives and save their parsed/ output as the reference
    python3 tests/perf/bench.py ref  <work-dir>
    # rebuild with the current code, time it, and compare byte for byte
    python3 tests/perf/bench.py check <work-dir>

Archives: the demo corpus, tests/corpus2, and synthetic 1k and 3k archives from
gen.py (Zipf-distributed names, so common names repeat as in real data)."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent                          # the code under test: this repository
FILES = ("claims.jsonl", "declared.json", "generic.json", "identical.jsonl", "ledger.jsonl", "parsed.yaml")
CODE = ("import sys; sys.path.insert(0, %r); from hydra import build; "
        "build.build_archive(sys.argv[1], now='2026-01-01T00:00:00+00:00')")


def archives(work: Path) -> dict[str, Path]:
    out = {}
    src = REPO / "src" / "hydra" / "template"
    for name, cols in (("demo", HERE.parent.parent / "examples" / "demo" / "collections"), ("corpus2", HERE.parent / "corpus2" / "collections")):
        root = work / "arch" / name
        if not root.exists():
            shutil.copytree(src, root)
            for f in cols.glob("*.json"):
                if f.name != "manifest.json":
                    shutil.copy(f, root / "collections" / f.name)
        out[name] = root
    for n in (1000, 3000):
        root = work / "arch" / f"synth{n}"
        if not root.exists():
            subprocess.run([sys.executable, str(HERE / "gen.py"), str(n), str(root), str(src)], check=True,
                           stdout=subprocess.DEVNULL)
        out[f"synth{n}"] = root
    return out


def build(root: Path) -> float:
    shutil.rmtree(root / ".hydra" / "parsed", ignore_errors=True)
    for f in ("collections/manifest.json",):
        (root / f).unlink(missing_ok=True)
    t = time.time()
    subprocess.run([sys.executable, "-c", CODE % str(REPO / "src"), str(root)], check=True,
                   env={**os.environ, "PYTHONHASHSEED": "0"})
    return time.time() - t


def main(mode: str, work: Path) -> int:
    bad = 0
    for name, root in archives(work).items():
        secs = build(root)
        ref = work / "ref" / name
        if mode == "ref":
            shutil.rmtree(ref, ignore_errors=True)
            shutil.copytree(root / ".hydra" / "parsed", ref)
            print(f"{name:10} {secs:6.1f}s  reference saved")
            continue
        diff = [f for f in FILES if (root / ".hydra" / "parsed" / f).read_bytes() != (ref / f).read_bytes()]
        bad += bool(diff)
        print(f"{name:10} {secs:6.1f}s  {'IDENTICAL' if not diff else 'DIFFERS: ' + ', '.join(diff)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2])))
