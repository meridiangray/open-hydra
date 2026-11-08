"""flagdata.py — fetch the flag SVGs the wiki draws (flags.py).

The source is two pinned npm packages (MIT — see NOTICE.md); `python -m hydra.wiki.flagdata` downloads them into
`assets/flags/<style>/<code>.svg` next to this file. The wheel build does the same (setup.py), so the repo itself
never stores the files — the folder is gitignored. `$HYDRA_FLAGS_DIR` still overrides the lot. Kept free of hydra
imports so setup.py can load it before the package exists.
"""
from __future__ import annotations

import io
import tarfile
import urllib.request
from pathlib import Path

DIR = Path(__file__).parent / "assets" / "flags"          # <style>/<code>.svg

LIBS = {                                                 # npm package -> (version, {style: folder in the tarball})
    "circle-flags": ("2.8.3", {"circle": "flags"}),
    "flag-icons": ("7.6.0", {"rect": "flags/4x3", "square": "flags/1x1"}),
}


def fetch(dest: Path = DIR) -> Path:
    for name, (ver, subs) in LIBS.items():
        url = f"https://registry.npmjs.org/{name}/-/{name}-{ver}.tgz"
        with urllib.request.urlopen(url, timeout=60) as r:
            blob = io.BytesIO(r.read())
        with tarfile.open(fileobj=blob, mode="r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                # Nested language/region flags can reuse a country's code (e.g. ca).
                # Only the package's direct flag files belong in the ISO-code lookup.
                targets = [dest / style / Path(m.name).name for style, sub in subs.items()
                           if Path(m.name).parent.as_posix() == f"package/{sub}" and m.name.endswith(".svg")]
                if Path(m.name).name.lower() in ("license", "license.md", "license.txt"):
                    targets.append(dest / name / Path(m.name).name)
                for target in targets:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tf.extractfile(m) as source:
                        target.write_bytes(source.read())
    return dest


if __name__ == "__main__":
    print(fetch())
