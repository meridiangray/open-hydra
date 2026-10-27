"""A build depends on the records, never on the order they arrive in: the
property that makes "re-ingest = rebuild" true (the only carried state is
verdicts.yaml). Nodes, parents, referents, roots and every ledger row (id,
status, group) must match under shuffled record order, prefixed or not."""
import random


import test_fold as f  # noqa: E402
from hydra import ingest as prefixes  # noqa: E402
from hydra.shape import reads, rules  # noqa: E402
from hydra.structure import fold  # noqa: E402


def _sig(recs):
    fam = fold.load_direction(f.DIRECTION)
    ir = reads.build_reads(recs, rules.compile_rules(None, None, direction=fam),
                           direction=fam, params_dir=f.PARAMS)
    nodes = {i: (n["caption"], n["schema"], n["pid"], tuple(n["referents"]), n["position"])
             for i, n in ir["nodes"].items()}
    ledger = sorted((r["id"], r["rel"], r["status"], r.get("group") or "") for r in ir["ledger"])
    return nodes, sorted(ir["roots"]), ledger


def _shuffled(recs, seed):
    out = list(recs)
    random.Random(seed).shuffle(out)
    return out


def test_record_order_does_not_change_the_build():
    f._load()
    recs = f._load_demo_records()
    ref = _sig(recs)
    for seed in (0, 1):
        assert _sig(_shuffled(recs, seed)) == ref


def test_record_order_does_not_change_the_tagged_build():
    f._load()
    recs = prefixes.prefix_records(f._load_demo_records())[0]
    assert _sig(_shuffled(recs, 2)) == _sig(recs)
