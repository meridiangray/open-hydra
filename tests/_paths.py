"""Where the code under test and the demo archive are: the repository this folder sits in."""
from pathlib import Path

TESTS = Path(__file__).resolve().parent
HYDRA = TESTS.parent
SRC = HYDRA / "src"
TEMPLATE = SRC / "hydra" / "template"
DEMO = HYDRA / "tests" / "corpus" / "engine-fixture" / "collections"      # engine regression data; the public demo is examples/demo
