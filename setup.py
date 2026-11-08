"""setup.py — build-time only: download the flag SVGs (pinned npm packages, src/hydra/wiki/flagdata.py)
into the wheel, so an installed hydra draws flags while the repo stores none of them."""
import importlib.util
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

_spec = importlib.util.spec_from_file_location("flagdata", Path(__file__).parent / "src/hydra/wiki/flagdata.py")
flagdata = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flagdata)


class build_py(build_py):
    def run(self):
        super().run()
        flagdata.fetch(Path(self.build_lib) / "hydra/wiki/assets/flags")


setup(cmdclass={"build_py": build_py})
