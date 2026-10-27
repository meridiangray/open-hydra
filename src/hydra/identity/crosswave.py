"""crosswave.py — merging compatible classes that resolve in different waves.

A class waits for a later wave when it promotes an entity-typed property to
match/distinct, so a generic record and its specific subtype (`Asset`/
`BankAccount`, `Event`/`Trip`, `Identification`/`Passport`) never meet inside a
wave. This pass runs after every wave, over settled survivors only, decides
each such pair by the same rules, and absorbs an auto or confirmed one into the
more specific record. Limit: earlier-wave rows that pointed at the two records
are not re-decided."""
from __future__ import annotations

from functools import partial

from hydra import schema
from hydra.identity import match, similar
from hydra.review import ids, ledger as review, verdicts as vd
from hydra.shape.captions import caption


def reconcile(passes, indices: dict, survivors: dict, verdicts: dict,
                          identical: list, pcs: dict, resolved: dict) -> None:
    """Decide the cross-wave pairs with the same rules as a wave (specific class's
    params, references already resolved), guard kinds and group them on the rules'
    own statuses, then apply verdicts (so a confirm picks a branch of a fork),
    cascade, and absorb each auto or confirmed row into the more specific record."""
    wave_of = {c: i for i, w in enumerate(passes) for c in w}
    live = sorted(c for c, idx in indices.items()
                  if idx.records and c in wave_of and not schema.is_a(c, "Similar"))
    pairs = [(a, b) for a in live for b in live
             if a < b and wave_of[a] != wave_of[b] and match.compat(a, b)]
    if not pairs:
        return
    final = {rid: rec for idx in indices.values() for rid, rec in idx.records.items()}
    have = {e["id"] for e in identical}
    rows, seen = [], set()
    for a_cls, b_cls in pairs:
        for x_cls, y_cls in ((a_cls, b_cls), (b_cls, a_cls)):
            for rid, rec in sorted(indices[x_cls].records.items()):
                for other in sorted(indices[y_cls].candidate_ids(rec, pcs[x_cls])):
                    pair = tuple(sorted((rid, other)))
                    key = ids.merge_key(*pair)
                    if pair[0] == pair[1] or pair in seen or key in have:
                        continue
                    seen.add(pair)
                    rec_a, rec_b = final[pair[0]], final[pair[1]]
                    decided = match.decide(rec_a, rec_b, pcs, resolved)
                    if decided is None:
                        continue
                    status, criteria, _hows = decided
                    row = {
                        "id": key, "rel": "sameAs", "a": pair[0], "b": pair[1],
                        "acap": caption(rec_a, verdicts),
                        "bcap": caption(rec_b, verdicts),
                        "status": status, "criteria": criteria + " (across waves)",
                        "basis": review.row_basis(rec_a, pcs[rec_a["schema"]],
                                                  rec_b, pcs[rec_b["schema"]]),
                        "matcher": "hydra/merge", "cross_wave": True,
                    }
                    rows.append(row)
    if not rows:
        return
    # forks are found and grouped on the rules' own verdicts, THEN a human's
    # verdict is applied, so an explicit confirm picks a branch of the fork
    # instead of tripping the kind guard
    match.guard_kinds(rows, final)
    review.assign_groups(rows)
    for row in rows:
        vd.apply(row, verdicts.get(row["id"]))
    review.cascade(rows)
    identical.extend(rows)

    find = partial(ids.survivor, survivors)

    for row in rows:
        if row["status"] not in ("auto", "confirmed"):
            continue
        a, b = find(row["a"]), find(row["b"])
        if a == b:
            continue
        final = {rid: rec for idx in indices.values() for rid, rec in idx.records.items()}
        if a not in final or b not in final or not match.compat(final[a]["schema"], final[b]["schema"]):
            row["status"] = "conflict"
            row["criteria"] += " (would join incompatible kinds)"
            continue
        similar.absorb(a, b, final, indices, survivors)
