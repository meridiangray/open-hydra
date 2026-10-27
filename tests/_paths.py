"""Where the code under test and the demo archive are: the repository this folder sits in."""
from pathlib import Path

TESTS = Path(__file__).resolve().parent
HYDRA = TESTS.parent
SRC = HYDRA / "src"
TEMPLATE = SRC / "hydra" / "template"
DEMO = HYDRA / "examples" / "demo" / "collections"
