"""Review rows: the questions the engine declines to guess.

Everything here is derived from the merge/fold reports plus the verdicts
(verdicts.py reads and applies them; ids.py builds their keys). A `rejected`
sameAs is never undone by new data; `contradictions()` surfaces the case where
other confirmed links merge a rejected pair anyway.

An ambiguous reference (bare "Wallace Wright" -> Wallace / Wallace Jr.) is never
auto-resolved: it becomes a `references` row with ranked candidates. One with no
candidate at all becomes a row with status `unresolved`. Rows are grouped by
`schema.prop`, so a cluster of identical failures reads as one problem."""
from __future__ import annotations

import hashlib

from hydra import schema
from hydra.identity import index as index_mod, order
from hydra.review import ids


def is_provenance_pointer(range_: str | None) -> bool:
    """A reference to a Document/Pages record is evidence, not an entity
    question: those stay id/content-addressed on purpose and
    are attached as `linked` evidence, never put to a human as a pick."""
    return bool(range_ and range_ in schema.SCHEMA and schema.is_a(range_, "Document"))


def reference_rows(entries: list[dict], pinned: list[dict], indices: dict,
                   schema_of: dict[str, str], schema_names: list[str],
                   verdicts: dict | None = None) -> list[dict]:
    """`entries`: ambiguous/unresolved reports ({record, prop, value,
    candidates?, kind}); `pinned`: {record, prop, value, pinned}. -> ledger
    rows, one per distinct (record, prop, value), deterministic order."""
    verdicts = verdicts or {}
    rows: dict[str, dict] = {}

    def base(e, status):
        rec_schema = schema_of.get(e["record"], "")
        pd = (schema.resolve(rec_schema)["props"].get(e["prop"]) if rec_schema in schema.SCHEMA else None) or {}
        return {"id": ids.reference_key(e["record"], e["prop"], e["value"]), "rel": "references",
                "record": e["record"], "schema": rec_schema, "prop": e["prop"],
                "value": e["value"], "group": f"{rec_schema}.{e['prop']}",
                "range": pd.get("range"), "status": status, "choice": None,
                "candidates": [], "matcher": "hydra/references"}

    for e in entries:
        kind = e.get("kind", "ambiguous" if e.get("candidates") else "unresolved")
        row = base(e, "proposed" if kind == "ambiguous" else "unresolved")
        if is_provenance_pointer(row["range"]):
            continue
        conc = (order.concrete_classes_for_range(row["range"], schema_names)
                if row["range"] else set(indices))
        scoped = {c: i for c, i in indices.items() if c in conc}
        seen = set()
        for h in index_mod.search(e["value"], scoped):
            if h.record_id in seen:
                continue
            seen.add(h.record_id)
            row["candidates"].append({"id": h.record_id, "caption": h.caption,
                                      "schema": h.schema, "how": h.how,
                                      "query_tokens": h.query_tokens,
                                      "candidate_tokens": h.candidate_tokens,
                                      "shared_tokens": h.shared_tokens})
        if verdicts.get(row["id"]) == "none":       # a person said: it names nothing here
            row["status"] = "dismissed"
        rows.setdefault(row["id"], row)
    for e in pinned:
        row = base(e, "pinned")
        row["choice"] = e["pinned"]
        rows[row["id"]] = row
    return [rows[k] for k in sorted(rows)]


def reference_groups(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        if r["status"] != "pinned":
            out[r["group"]] = out.get(r["group"], 0) + 1
    return dict(sorted(out.items()))


def contradictions(identical: list[dict], survivors: dict, by_id: dict | None = None,
                   params_dir=None) -> list[dict]:
    """Rejected (NOT-sameAs) rows whose two ends nonetheless share a survivor;
    each carries the chain of links that joined them (`trace.py`)."""
    from hydra.review import trace
    return trace.contradictions(identical, survivors, by_id, params_dir)


# ---- sameAs rows: basis, N-of-1 groups ------------------------------------


def row_basis(rec_a: dict, pc_a: dict, rec_b: dict, pc_b: dict) -> str:
    """Hash of exactly the values that justified (or would justify) a
    sameAs row: every match/distinct-category property of both records,
    case/space-normalized. New data that changes any of them changes the
    basis, so a decision made on the old basis can be told apart from one
    still resting on the same evidence."""
    parts = []
    for tag, rec, pcs in (("a", rec_a, pc_a), ("b", rec_b, pc_b)):
        for prop, vals in (rec.get("properties") or {}).items():
            pc = pcs.get(prop)
            if not pc or not (pc.match or pc.distinct):
                continue
            for v in sorted(vals or []):
                parts.append(f"{tag}\x1f{prop}\x1f{' '.join(str(v).lower().split())}")
    return hashlib.sha256("\x1e".join(sorted(parts)).encode()).hexdigest()[:16]


def assign_groups(rows: list[dict]) -> None:
    """Mark N-of-1 forks. Candidates are the non-auto sameAs rows (a row's
    membership must not change when someone decides it, so decided rows
    count). The focus of a row is its end with more incident candidate
    rows (tie: smaller id); a focus with 2+ rows names a group — e.g. a
    bare name matching two real people. Singletons get `group: None`."""
    cand = [r for r in rows if r.get("rel") == "sameAs" and r.get("status") != "auto"]
    degree: dict[str, int] = {}
    for r in cand:
        for end in (r["a"], r["b"]):
            degree[end] = degree.get(end, 0) + 1
    focus_of = {}
    for r in cand:
        a, b = r["a"], r["b"]
        focus_of[r["id"]] = max((a, b), key=lambda x: (degree[x], [-ord(c) for c in x]))
    count: dict[str, int] = {}
    for f in focus_of.values():
        count[f] = count.get(f, 0) + 1
    for r in rows:
        f = focus_of.get(r.get("id"))
        r["group"] = ids.group_key(f) if f and count[f] > 1 else None


def cascade(rows: list[dict]) -> None:
    """Confirming one row of a group rejects its still-`proposed` siblings
    (derived each build, never written to verdicts.yaml). A sibling the user
    already decided is left alone, so two explicit confirms stay both."""
    confirmed = {r["group"]: r["id"] for r in rows
                 if r.get("group") and r.get("status") == "confirmed"}
    for r in rows:
        g = r.get("group")
        if g in confirmed and r.get("status") == "proposed":
            r["status"], r["cascaded_from"] = "rejected", confirmed[g]
            r["criteria"] = f"{r['criteria']} (sibling of confirmed {confirmed[g]})"


def scope_basis(basis: str, scope_a: list, scope_b: list) -> str:
    """Fold the scope evidence into a row's basis, so a confirm made on a
    scope that later changes (a phantom graduates, a cycle appears) goes
    `confirmed-stale` like any other drift."""
    parts = sorted(f"a\x1f{k}\x1f{kind}" for k, kind in scope_a) + \
        sorted(f"b\x1f{k}\x1f{kind}" for k, kind in scope_b)
    return hashlib.sha256((basis + "\x1e" + "\x1e".join(parts)).encode()).hexdigest()[:16]
