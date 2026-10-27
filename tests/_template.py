"""copy_template(): the template, copied from a /tmp mirror made once per test run
(the repo may sit on a slow mount; copying ~200 files from it per test is most
of a small test's time)."""
import atexit
import shutil
import tempfile
from pathlib import Path
from _paths import TEMPLATE as TEMPLATE_DIR  # noqa: E402

SRC = TEMPLATE_DIR
_MIRROR: list[Path] = []


def copy_template(dest, sub: str = "") -> Path:
    if not _MIRROR:
        d = Path(tempfile.mkdtemp(prefix="hydra-template-")) / "template"
        shutil.copytree(SRC, d)
        atexit.register(shutil.rmtree, d.parent, True)
        _MIRROR.append(d)
    shutil.copytree(_MIRROR[0] / sub if sub else _MIRROR[0], dest)
    return Path(dest)
