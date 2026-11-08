from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from hydra import resources
from hydra.universe import build as ubuild
from hydra.wiki import site


def shell_path(given=None) -> Path:
    given = given or os.environ.get("HYDRA_DESKTOP_SHELL")
    if given:
        path = Path(given).expanduser().resolve()
    else:
        name = "hydra-desktop-shell.exe" if os.name == "nt" else "hydra-desktop-shell"
        base = Path(__file__).resolve().parents[2] / "desktop" / "build"
        candidates = [base / "Release" / name, base / name]
        found = shutil.which(name)
        path = next((p for p in candidates if p.is_file()), Path(found) if found else candidates[0])
    if not path.is_file():
        raise FileNotFoundError(f"Build the Saucer shell first: cmake -S desktop -B desktop/build; "
                                f"cmake --build desktop/build --config Release. "
                                f"Use --shell PATH for a shell outside this checkout (looked for {path}).")
    return path


def pick_archive() -> str:
    import tkinter
    from tkinter import filedialog

    window = tkinter.Tk()
    window.withdraw()
    try:
        return filedialog.askdirectory(title="Open a Hydra archive", mustexist=True)
    finally:
        window.destroy()


def run_shell(args, timeout=None) -> int:
    with subprocess.Popen(args) as process:
        try:
            return process.wait(timeout=timeout)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def launch(archive, shell=None, *, build=False, theme=None, smoke_test=False) -> int:
    executable = shell_path(shell)
    root = resources.archive(str(Path(archive).expanduser().resolve()), read_only=True, built=False)
    if not ubuild.pages_current(root):
        if not build:
            raise ValueError("This archive's wiki pages are missing or stale. Build the universe first, "
                             "or pass --build to explicitly rebuild before opening.")
        ubuild.build(root)
    server, _ = site.serve(root, port=0, host="127.0.0.1", theme=theme)
    worker = threading.Thread(target=server.serve_forever, name="hydra-wiki", daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    args = [str(executable), url]
    if smoke_test:
        args.append("--smoke-test")
    try:
        return run_shell(args, timeout=45 if smoke_test else None)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Open a Hydra archive in a Saucer desktop window.")
    parser.add_argument("archive", nargs="?", help="Archive folder or .hydra pack; omitted opens a folder picker")
    parser.add_argument("--shell", help="Path to the built hydra-desktop executable")
    parser.add_argument("--build", action="store_true", help="Explicitly rebuild missing or stale universe pages")
    parser.add_argument("--theme", choices=tuple(site.THEMES))
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        archive = args.archive or pick_archive()
        if not archive:
            return 0
        return launch(archive, args.shell, build=args.build, theme=args.theme, smoke_test=args.smoke_test)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"hydra-desktop: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
