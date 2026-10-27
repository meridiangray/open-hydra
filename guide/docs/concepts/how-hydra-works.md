# How Hydra works

Hydra acts as a compiler. It reads everything in `collections/`, merges records that are the same entity, places each one in a hierarchy, and turns everything it can't settle into questions for review. The result can be used as a source for display in a UI.

## Review

Instead of strict field adherence, Hydra assumes your fields are correct. It then proposes a set of `review` tasks to clarify key details, identify conflicts, and automatically merge identical entities.

Your answers are saved in the archive and applied on every later build. If you merged all your claims, you would produce the dataset already in `collections/`.

`hydra-ctl todo` counts what is open, by kind:

| Kind | Asks |
|---|---|
| merges | Are these two records the same entity? |
| references | Which record does this name mean? |
| placements | Which parent should the tree draw this record under? |
| stale | A decision's evidence changed. Is it still right? |
| contradictions | Do two sources disagree on a value? |
| verdicts | A saved decision no longer matches a question. Keep it? |

[Reviewing](../guides/reviewing.md) shows how to answer each one.

## Trees

A record can have several parents: the organization it is a member of, the company that employs it, the person it reports to. Hydra draws every record once, under one parent, like an org chart, and lists its other parents under it so nothing is hidden.

Choosing the parent only changes how the tree is drawn. The data in the entity's fields does not change.

## What a build writes

`hydra-ctl build` reads `collections/`, `.hydra/sources/entries/` and the rules, and writes `.hydra/parsed/`:

| File | Holds |
|---|---|
| `generic.json`, `declared.json` | The two reads of the hierarchy, one with the generic positions only and one with yours |
| `claims.jsonl` | Every value of every entity, with the record and collection it came from |
| `identical.jsonl` | The merges |
| `ledger.jsonl` | The placements, references and other questions, each with its status |
| `parsed.yaml` | The combined position rules the build used |
| `build.yaml` | The summary: counts, issues, when it was built |

Nothing is carried from one build to the next except your decisions. Two builds of the same archive give the same files, byte for byte, and a build that would change nothing is skipped.

`.hydra/cache/` keeps parsed config between runs so builds stay fast. It is safe to delete; the next build is just slower.
