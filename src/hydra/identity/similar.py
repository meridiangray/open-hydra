"""similar.py — `Similar` records: an analyst's "these are the same thing".

A `Similar` record names two things (`candidate`, `match`) and asserts they are
one. Each side is looked up with the permissive `index.search()`, because the
point of the record is often a name that is itself ambiguous ("Heisenberg"). Every
pair it yields is a `proposed` sameAs row, never auto; the hits for one value
form a group, so confirming one rejects the others. Runs after every merge pass,
against the final indices, so both ends are already-merged survivors."""
from __future__ import annotations

from functools import partial

from hydra import schema
from hydra.identity import index as index_mod, match
from hydra.review import ids, ledger as review, verdicts as vd
from hydra.shape.captions import caption


def apply_similar(records: list[dict], by_id: dict, schema_names: list[str],
                   indices: dict, survivors: dict, verdicts: dict,
                   identical: list, prop_classes_by_schema: dict) -> None:
    """Turn every `Similar` record into proposed sameAs rows. Each side is looked
    up with `index.search()` against the final indices; every distinct (candidate
    hit, match hit) pair becomes a row, and the hits for one value share a group.
    A row an ordinary pass already made is marked as asserted instead. Only a
    confirmed row of two compatible kinds is absorbed; an incompatible one becomes
    a `conflict`."""
    find = partial(ids.survivor, survivors)

    def final_record(rid: str) -> dict:
        sname = by_id.get(rid, {}).get("schema")
        idx = indices.get(sname)
        return (idx.records.get(rid) if idx else None) or by_id.get(rid, {"id": rid, "properties": {}})

    by_key = {e["id"]: e for e in identical}
    absorbed: dict[str, list[str]] = {}
    for x in survivors:
        absorbed.setdefault(find(x), []).append(x)

    def members(rid: str) -> list[str]:
        return [rid] + absorbed.get(rid, [])

    seen_pairs: set[tuple[str, str]] = set()
    sim_rows: list[dict] = []
    for r in records:
        if not schema.is_a(r.get("schema", ""), "Similar"):
            continue
        props = r.get("properties") or {}
        for cv in props.get("candidate") or []:
            cand_hits = [h.record_id for h in index_mod.search(cv, indices)]
            for mv in props.get("match") or []:
                match_hits = [h.record_id for h in index_mod.search(mv, indices)]
                asked: list[dict] = []        # the rows answering THIS one question
                # rows an ordinary pass already made for this pair — looked up
                # through every record each hit has absorbed, since a confirmed
                # merge has already folded one end away
                for cid in sorted({x for h in cand_hits for x in members(h)}):
                    for mid in sorted({x for h in match_hits for x in members(h)}):
                        old = by_key.get(ids.merge_key(*sorted((cid, mid)))) if cid != mid else None
                        if old is not None:
                            if old not in asked:
                                asked.append(old)
                            if not old.get("similar"):
                                old["similar"] = True
                                old["criteria"] += " (asserted by a Similar record)"
                            seen_pairs.add(tuple(sorted((find(cid), find(mid)))))
                for cid in cand_hits:
                    for mid in match_hits:
                        a, b = find(cid), find(mid)
                        if a == b:
                            continue
                        pair = tuple(sorted((a, b)))
                        key = ids.merge_key(*pair)
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)
                        rec_a, rec_b = final_record(pair[0]), final_record(pair[1])
                        row = {
                            "id": key, "rel": "sameAs", "a": pair[0], "b": pair[1],
                            "acap": caption(rec_a, verdicts),
                            "bcap": caption(rec_b, verdicts),
                            "status": "proposed", "criteria": "Similar record",
                            "similar": True,
                            "basis": review.row_basis(
                                rec_a, prop_classes_by_schema.get(rec_a.get("schema"), {}),
                                rec_b, prop_classes_by_schema.get(rec_b.get("schema"), {})),
                            "matcher": "hydra/merge",
                        }
                        vd.apply(row, verdicts.get(key))
                        sim_rows.append(row)
                        by_key[key] = row
                        asked.append(row)
                        identical.append(row)
                # Candidate hits for one Similar value are alternatives of one
                # question ("which record does `Heisenberg` mean?"): that is a
                # fork by construction, whatever the per-record degrees say.
                if len(asked) > 1:
                    gid = ids.similar_group_key(r["id"], cv, mv)
                    for row in asked:
                        row["group"] = row.get("group") or gid
    # one confirm rejects its still-proposed siblings before anything is
    # absorbed, so a rejected sibling never merges
    review.cascade(identical)
    # resolved at absorb time, as in crosswave: an earlier absorb may already
    # have folded a row's record into another survivor
    for row in sim_rows:
        if row["status"] != "confirmed":
            continue
        a, b = find(row["a"]), find(row["b"])
        if a == b:
            continue
        final = {rid: rec for idx in indices.values() for rid, rec in idx.records.items()}
        sa, sb = final[a]["schema"], final[b]["schema"]
        if not match.compat(sa, sb):
            row["status"] = "conflict"
            row["criteria"] += f" (different kinds of thing: {sa} vs {sb})"
            continue
        absorb(a, b, final, indices, survivors)


def absorb(id_a: str, id_b: str, by_id: dict, indices: dict,
                    survivors: dict) -> None:
    """Fold two confirmed-same records of COMPATIBLE schemas (equal, or one
    an ancestor of the other) into one survivor. The more specific schema
    keeps the id, so a generic LegalEntity absorbed into a Person leaves a
    Person; equal schemas fall back to the richer record. Incompatible kinds
    never reach here (the caller turns them into a `conflict` row) — a raw
    property-KEY count across two different vocabularies is not a meaningful
    comparison, which is how an Organization once swallowed Walter White."""
    sa, sb = by_id[id_a]["schema"], by_id[id_b]["schema"]
    ra = indices[sa].records.get(id_a, by_id[id_a])
    rb = indices[sb].records.get(id_b, by_id[id_b])
    if bool(by_id[id_a].get("_stub")) != bool(by_id[id_b].get("_stub")):
        a_wins = not by_id[id_a].get("_stub")                  # a stub never survives
    elif sa == sb:
        a_wins = len(ra.get("properties") or {}) >= len(rb.get("properties") or {})
    else:
        a_wins = match.specific(sa, sb) == sa
    if a_wins:
        keep, keep_sname, drop, drop_rec, drop_sname = id_a, sa, id_b, rb, sb
    else:
        keep, keep_sname, drop, drop_rec, drop_sname = id_b, sb, id_a, ra, sa

    survivors[drop] = keep
    keep_rec = indices[keep_sname].records.setdefault(keep, by_id[keep])
    keep_props = keep_rec.setdefault("properties", {})
    for prop, vals in (drop_rec.get("properties") or {}).items():
        bucket = keep_props.setdefault(prop, [])
        for v in vals:
            if v not in bucket:
                bucket.append(v)
    indices[drop_sname].records.pop(drop, None)
    indices[drop_sname].name_values.pop(drop, None)
