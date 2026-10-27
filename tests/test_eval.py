"""The labelled corpus (tests/corpus2/, merge_eval.py): what hydra must and must
not do with it. Numbers are asserted as floors and exact traps, not tuned."""

import pytest


import merge_eval as me  # noqa: E402


@pytest.fixture(scope="module")
def ev(tmp_path_factory):
    return me.evaluate(tmp_path_factory.mktemp("eval"))


def test_no_automatic_merge_is_wrong(ev):
    assert ev["hydra_auto"]["precision"] == 1.0


def test_hydra_beats_the_exact_name_baseline(ev):
    assert ev["hydra_auto"]["recall"] >= ev["baseline"]["recall"]
    assert ev["hydra_surfaced"]["recall"] > ev["baseline"]["recall"]
    assert ev["baseline"]["precision"] < 1.0          # it merges the two Jürgen Weiß


def test_the_traps_never_merge(ev):
    for trap in ("leaks:p-weiss-jr", "leaks:c-nordwind-ltd", "press:p-initial"):
        assert not any(trap in p for p in ev["merged"]), trap


def test_a_pair_that_only_shares_a_word_is_not_proposed(ev):
    assert frozenset(("leaks:c-nordwind-ltd", "registry:c-reefer")) not in ev["proposed"]


def test_the_company_group_chain_is_built(ev):
    import json
    nodes = json.loads((ev["root"] / ".hydra" / "parsed" / "generic.json").read_text(encoding="utf-8"))["nodes"]
    pid = {k: n["pid"] for k, n in nodes.items()}
    assert pid["registry:c-polska"] == "registry:c-logistik"
    assert pid["registry:c-logistik"] == "registry:c-holding"
    assert pid["registry:c-reefer"] == "registry:c-holding"      # via the leaked Ownership
