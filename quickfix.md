# quickfix: `hydra-ctl export` graph filters

Two flags for `hydra-ctl export` graph formats (`csv`, `graphml`, and a future
`mermaid`), plus one label bug found while inspecting the output. All changes
live in `src/hydra/cli/export.py`, inside `graph()` — no new plumbing.

## 1. `--with-sources` — evidence layer, off by default

Today every entity's `sources` citation becomes an edge to the source
Document (25 of 54 edges on demo-pollard). Default graph export should drop
the evidence layer entirely:

- Skip prop-link edges with `p == "sources"` (after `FTM_RENAMES`, this also
  covers FtM `proof`).
- Skip Document-family nodes: `schema.is_a(e["schema"], "Document")`.
  Edges can't dangle — they're only emitted when both ends are in `nodes`.

`--with-sources` restores today's behavior exactly (docs + citation edges).

Why convergent edges are safe scoped to source docs: `Thing.proof` (exported
as `sources`) has `range: Document`, so the *only* edges that can ever point
at a Document are evidence edges — `sources`/`proof`, `Document.parent`,
`Mention.document`, doc↔doc `sameAs`. Nothing from the entity side can leak
in. Off = entity graph, on = entity graph + evidence layer. No gray zone.

Caveat: a corrupt `sources` value pointing at a non-Document id still draws
(`check_records` doesn't range-validate link targets). Leave lax — a bad
citation renders as a visibly wrong edge, which is better than hiding it.
Optional strictness: `is_a(target, "Document")` when classifying.

Scope: graph formats only. The `ftm` export keeps the Document + `sources`
props unconditionally — citations are how entities link to evidence in FtM.

## 2. `--orphans` — unlinked nodes, off by default

A node with no remaining edges (after the sources filter) is skipped unless
`--orphans` is passed. Symmetric with `--with-sources`: real data like CIA /
FBI records with no stated relationships stays out of a graph render by
default, opt-in when wanted.

## 3. Bug: Associate/Family lose their edge labels

`graph()` reads only `props.get("role")` for the edge label, but `Associate`
and `Family` store their word in `relationship`. Today "wife",
"first handler" vanish from csv/graphml exports — the edges exist unlabeled.

```python
"role": ";".join(props.get("role") or props.get("relationship") or []),
```

Same function, fold into the same change.

## Tests

- csv export: edge count drops by the `*.sources` count; Document absent from
  `nodes.csv`; `--with-sources` restores both.
- orphan node absent by default, present with `--orphans`.
- an `Associate` edge's `role` column carries its `relationship` word.
