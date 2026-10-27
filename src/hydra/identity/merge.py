"""Layer 4b: identity merge.

Walks the waves from `order.resolve_order()`. For each wave: resolve the
entity-typed match/distinct values against already-merged records, generate
candidate pairs from the indices (same class, or is-a compatible classes), and
decide each pair with `match.decide()`:

    a match, but a distinct field differs  proposed, never auto
    nothing matched                     no row, whatever differs
    identifier or resolved-entity match auto
    exact name                          auto, unless both records are scope-
                                        bearing; then shared organization
                                        scope decides (scope.py)
    soft exact (address, date) only     proposed, or auto if neither is named
    word-subset name                    proposed

Verdicts are applied (basis-aware, verdicts.py), groups and cascades assigned
(review.py), kinds guarded, then auto/confirmed rows are unioned and merged
records built: the survivor is the most specific schema, then the richer
record, and keeps its own id. After the waves, `crosswave.reconcile()` and
`similar.apply_similar()` run. A reference that fits several records is never
guessed: it is reported as ambiguous."""
from __future__ import annotations

from functools import partial

from pathlib import Path

from hydra import schema
from hydra.identity import (
    classify, crosswave, index as index_mod, match, order, scope as scope_mod, similar,
)
from hydra.review import ids, ledger as review, verdicts as vd
from hydra.shape.captions import caption






resolve_reference = match.resolve_reference     # the public resolver, kept here for callers



def merge(records: list[dict], schema_names: list[str], params_dir: str | Path | None = None,
          verdicts: dict | None = None, pins: dict | None = None, direction: dict | None = None) -> dict:
    """See `_merge`; param files are read once for the whole pass."""
    with classify.frozen_params(params_dir):
        return _merge(records, schema_names, params_dir=params_dir, verdicts=verdicts, pins=pins,
                      direction=direction)


def _merge(records: list[dict], schema_names: list[str],
          params_dir: str | Path | None = None, verdicts: dict | None = None,
          pins: dict | None = None, direction: dict | None = None) -> dict:
    """records + schema/param context -> {
        "survivors": {record_id: survivor_id},
        "identical": [ {id, rel: "sameAs", a, b, status, criteria, group,
                        basis, ...} ],
        "claims": [ {entity, record, prop, value, schema, collection, source} ],
        "report": {"ambiguous_references": [...], "unresolved_references": [...]},
    }
    `verdicts`: {ledger_id: "confirmed"|"rejected"} — simple override only
    (see module docstring for what's deferred)."""
    verdicts = verdicts or {}
    pins = pins if pins is not None else vd.pins_from(verdicts)
    sfams = scope_mod.scope_families(direction, schema_names) if direction else []
    containers = scope_mod.container_classes(sfams)
    passes = order.resolve_order(schema_names, params_dir)
    prop_classes_by_schema = {s: classify.classify(s, params_dir) for s in schema_names}
    by_id = {r["id"]: r for r in records}

    survivors: dict[str, str] = {}
    identical: list[dict] = []
    report = {"ambiguous_references": [], "unresolved_references": [],
              "pinned_references": []}
    indices: dict[str, index_mod.ClassIndex] = {}

    def _exists(rid: str) -> bool:
        return rid in by_id or any(rid in i.records for i in indices.values())

    find = partial(ids.survivor, survivors)

    resolved_all: dict[tuple[str, str], tuple] = {}
    for wave in passes:
        classes = [c for c in sorted(wave) if not schema.is_a(c, "Similar")]
        for c in sorted(wave):
            if schema.is_a(c, "Similar"):
                indices.setdefault(c, index_mod.ClassIndex(schema_name=c))
                continue  # handled after every pass, see similar.apply_similar below
        class_recs = {c: [r for r in records if r.get("schema") == c] for c in classes}
        for c in classes:
            if not class_recs[c]:
                indices[c] = index_mod.ClassIndex(schema_name=c)
        active = [c for c in classes if class_recs[c]]
        if not active:
            continue
        pcs = prop_classes_by_schema

        resolved: dict[tuple[str, str], tuple[str | None, str, list[str]]] = {}
        for c in active:
            for r in class_recs[c]:
                for prop, pc in pcs[c].items():
                    if pc.ftm_type != "entity" or not (pc.match or pc.distinct):
                        continue
                    for v in (r.get("properties") or {}).get(prop) or []:
                        pin = vd.pin_target(pins, r["id"], prop, v, _exists)
                        if pin:
                            report["pinned_references"].append(
                                {"record": r["id"], "prop": prop, "value": v, "pinned": pin})
                            resolved[(r["id"], prop)] = (pin, "pinned", [pin])
                            continue
                        hit = match.id_link(r, prop, v, pc.range, indices)
                        res = (hit, "id", [hit]) if hit else match.resolve_reference(v, pc.range, schema_names, indices)
                        resolved[(r["id"], prop)] = res
                        if res[1] == "ambiguous":
                            report["ambiguous_references"].append(
                                {"record": r["id"], "prop": prop, "value": v, "candidates": res[2]})
                        elif res[1] == "unresolved":
                            report["unresolved_references"].append(
                                {"record": r["id"], "prop": prop, "value": v})

        resolved_all.update(resolved)
        idx_by_class = {c: index_mod.build_index(class_recs[c], c, pcs[c]) for c in active}
        compat_of = {c: [d for d in active if match.compat(c, d)] for c in active}
        pass_start = len(identical)
        seen_pairs: set[tuple[str, str]] = set()
        sigs: dict[str, tuple] = {}

        def sig(rec, c):
            if rec["id"] not in sigs:
                sigs[rec["id"]] = match.signature(rec, pcs[c])
            return sigs[rec["id"]]

        for c in active:
            for r in class_recs[c]:
                for d in compat_of[c]:
                    safe = c == d and pcs[c].token_safe
                    found = (idx_by_class[d].candidate_ids_safe(r, pcs[c]) if safe
                             else idx_by_class[d].candidate_ids(r, pcs[c]))
                    for other_id in sorted(found):
                        pair = tuple(sorted((r["id"], other_id)))
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)
                        rec_a, rec_b = by_id[pair[0]], by_id[pair[1]]
                        if c == d and rec_a["schema"] == rec_b["schema"] == c and pcs[c].token_safe \
                                and not match.may_match(sig(rec_a, c), sig(rec_b, c)):
                            continue            # provably no row (match.may_match)
                        decided = match.decide(rec_a, rec_b, pcs, resolved)
                        if decided is None:
                            continue
                        status, criteria, match_hows = decided
                        key = ids.merge_key(*pair)
                        row = {
                            "id": key, "rel": "sameAs", "a": pair[0], "b": pair[1],
                            "acap": caption(rec_a, verdicts),
                            "bcap": caption(rec_b, verdicts),
                            "status": status, "criteria": criteria,
                            "basis": review.row_basis(rec_a, pcs[rec_a["schema"]],
                                                      rec_b, pcs[rec_b["schema"]]),
                            "matcher": "hydra/merge",
                        }
                        # an exact NAME match between two scope-bearing records
                        # waits for scope; identifier / resolved-entity matches
                        # are hard evidence and never do
                        row["scope_pending"] = bool(
                            containers and status == "auto" and "exact" in match_hows
                            and not match.is_hard(match_hows)
                            and rec_a["schema"] not in containers
                            and rec_b["schema"] not in containers)
                        if not row["scope_pending"]:
                            vd.apply(row, verdicts.get(key))
                        identical.append(row)
        this_pass = identical[pass_start:]
        wave_ids = {r["id"] for c in active for r in class_recs[c]}

        def settle(rows: list[dict], emit: bool):
            """Union the auto/confirmed rows (kind-guarded), then materialize
            merged records per class. `emit=False` is a dry run used only to
            learn who the containers are before scope is decided."""
            parent = {rid: rid for rid in sorted(wave_ids)}
            comp_schema = {rid: by_id[rid]["schema"] for rid in parent}

            def pfind(x: str) -> str:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for e in rows:
                if e["status"] not in ("auto", "confirmed"):
                    continue
                ra, rb = pfind(e["a"]), pfind(e["b"])
                if ra == rb:
                    continue
                combined = {comp_schema[ra], comp_schema[rb]}
                if not match.chain_ok(combined):
                    continue                      # match.guard_kinds already demoted this
                sa, sb = by_id[ra], by_id[rb]
                ka = (not sa.get("_stub"), match.depth(comp_schema[ra]), len(sa.get("properties") or {}))
                kb = (not sb.get("_stub"), match.depth(comp_schema[rb]), len(sb.get("properties") or {}))   # a stub never survives
                keep, drop = (ra, rb) if ka >= kb else (rb, ra)
                parent[drop] = keep
                comp_schema[keep] = match.most_specific(combined)

            merged_by_class: dict[str, list[dict]] = {c: [] for c in classes}
            groups: dict[str, list[str]] = {}
            for rid in parent:
                groups.setdefault(pfind(rid), []).append(rid)
            for keep, members in groups.items():
                base = by_id[keep]
                props: dict[str, list[str]] = {}
                for member_id in members:
                    mrec = by_id[member_id]
                    for prop, vals in (mrec.get("properties") or {}).items():
                        bucket = props.setdefault(prop, [])
                        for v in vals:
                            if v not in bucket:
                                bucket.append(v)
                final_schema = comp_schema[keep]
                merged_by_class[final_schema].append({**base, "properties": props, "schema": final_schema})
                if emit:
                    for member_id in members:
                        if member_id != keep:
                            survivors[member_id] = keep
            return pfind, merged_by_class

        pending = [e for e in this_pass if e.get("scope_pending")]
        if pending:
            base_rows = [e for e in this_pass if not e.get("scope_pending")]
            match.guard_kinds(base_rows, by_id)
            review.assign_groups(base_rows)
            review.cascade(base_rows)
            pf1, mbc1 = settle(base_rows, emit=False)
            tmp = dict(indices)
            for c in classes:
                tmp[c] = index_mod.build_index(mbc1[c], c, pcs[c])
            bearing = {c for c in classes if c not in containers}
            scopes = scope_mod.compute_scopes(
                records, sfams, bearing, pcs, tmp, schema_names, match.resolve_reference,
                find=lambda rid: pf1(rid) if rid in wave_ids else find(rid))
            for e in pending:
                sa_, sb_ = scopes.get(e["a"], []), scopes.get(e["b"], [])
                status, why, kind = scope_mod.decide(sa_, sb_)
                suffix = e["criteria"][e["criteria"].index(" (generic"):] if " (generic" in e["criteria"] else ""
                e["status"], e["criteria"] = status, why + suffix
                e["scope"] = {"a": [list(x) for x in sa_], "b": [list(x) for x in sb_], "kind": kind}
                e["basis"] = review.scope_basis(e["basis"], sa_, sb_)
                e["scope_pending"] = False
                vd.apply(e, verdicts.get(e["id"]))
        match.guard_kinds(this_pass, by_id)
        review.assign_groups(this_pass)
        review.cascade(this_pass)
        _pf, merged_by_class = settle(this_pass, emit=True)
        for c in classes:
            indices[c] = index_mod.build_index(merged_by_class[c], c, pcs[c])

    crosswave.reconcile(passes, indices, survivors, verdicts, identical,
                          prop_classes_by_schema, resolved_all)
    similar.apply_similar(records, by_id, schema_names, indices, survivors, verdicts,
                   identical, prop_classes_by_schema)
    # every sameAs row says which distinct fields its two records disagree on,
    # so a reviewer sees what a manual confirm would put side by side
    for e in identical:
        ra, rb = by_id.get(e.get("a")), by_id.get(e.get("b"))
        if e.get("rel") != "sameAs" or not ra or not rb:
            continue
        sp = match.specific(ra["schema"], rb["schema"]) if match.compat(ra["schema"], rb["schema"]) else None
        if sp:
            clashes = match.compare_detail(ra, rb, prop_classes_by_schema[sp], resolved_all)[2]
            if clashes:
                e["conflicts"] = clashes

    for entries in report.values():   # record order is not data
        entries.sort(key=lambda e: (e["record"], e["prop"], e["value"]))
    return {"survivors": survivors, "identical": identical, "claims": claims_of(records, survivors),
            "report": report, "indices": indices}


def claims_of(records: list[dict], survivors: dict) -> list[dict]:
    """One claim per value of every record: the entity it ended up in, and the
    record and collection that supplied it, so a value traces to its source
    record (and that record's `sources`) whichever pass merged it."""
    out = []
    for r in records:
        ent, coll = ids.survivor(survivors, r["id"]), r.get("_collection", "unknown")
        for prop, vals in (r.get("properties") or {}).items():
            for i, v in enumerate(vals):
                out.append((ent, prop, r["id"], i, {"entity": ent, "record": r["id"], "prop": prop, "value": v,
                                                     "schema": r["schema"], "collection": coll,
                                                     "source": f"collection:{coll}"}))
    out.sort(key=lambda t: t[:4])            # by entity, property, record; a record's values as written
    return [t[4] for t in out]
