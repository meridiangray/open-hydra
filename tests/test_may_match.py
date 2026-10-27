"""match.may_match() is a pre-check that lets the merge skip decide() for pairs that
cannot produce a row. It must never say no to a pair decide() would accept: checked
here on random pairs of every name-only ("token-safe") class, with names drawn from
a small vocabulary so that subsets, equalities and near-misses are all common."""
import random


import test_fold as t  # noqa: E402
from hydra import schema  # noqa: E402
from hydra.identity import classify, match  # noqa: E402

WORDS = ["Anna", "anna", "Ánna", "Lee", "Lee-Smith", "Smith", "Ltd", "Acme", "ACME", "Co.", "Bob", "Ray"]


def _rec(rid, sch, pcs, rnd):
    props = {}
    for p, pc in pcs.md:
        if pc.match and rnd.random() < 0.5:
            if pc.ftm_type in ("name", "address"):
                props[p] = [" ".join(rnd.sample(WORDS, rnd.randint(1, 3))) for _ in range(rnd.randint(1, 2))]
            else:
                props[p] = [rnd.choice(["X1", "x-1", "Y2", "a@b.c", "A@B.C"])]
    return {"id": rid, "schema": sch, "properties": props}


def test_may_match_never_rejects_a_pair_decide_accepts():
    t._load()
    rnd = random.Random(7)
    safe = [s for s in sorted(schema.SCHEMA) if not schema.SCHEMA[s].get("abstract")
            and classify.classify(s, t.PARAMS).token_safe]
    assert {"Person", "Company", "Organization"} <= set(safe)
    checked = accepted = 0
    for s in safe:
        pcs = classify.classify(s, t.PARAMS)
        if not any(pc.match for _, pc in pcs.md):
            continue
        for i in range(150):
            a, b = _rec(f"a{i}", s, pcs, rnd), _rec(f"b{i}", s, pcs, rnd)
            row = match.decide(a, b, {s: pcs}, {})
            ok = match.may_match(match.signature(a, pcs), match.signature(b, pcs))
            checked += 1
            if row is not None:
                accepted += 1
                assert ok, (s, a, b, row)
    assert checked > 3000 and accepted > 300
