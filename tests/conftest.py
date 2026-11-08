"""The suite's identity policy.

Most tests here exercise the name-merge engine: exact names merged, scope
deciding for people, generic records specializing, guards against forks. An
archive opts into that engine with `same_name: merge` (hydra.yaml or a type's
param file); the default is `review`, where only proof merges on its own. So
the suite runs with `merge` as the default (set once, before any fixture
builds an archive), and the tests of the default itself are marked `proof`."""
import pytest

from hydra.identity import classify


def pytest_configure(config):
    config.addinivalue_line("markers", "proof: runs with hydra's default same_name: review")
    classify.DEFAULT_SAME_NAME = "merge"


@pytest.fixture(autouse=True)
def _same_name_policy(request, monkeypatch):
    if request.node.get_closest_marker("proof") is not None:
        monkeypatch.setattr(classify, "DEFAULT_SAME_NAME", "review")
