# Reviewing

Hydra assumes your fields are correct, then asks you about what it can't settle itself: records that might be one entity, names that could mean several records, and records with more than one possible parent.

```sh
hydra-ctl todo              # count what is open, by kind
hydra-ctl todo --list       # each question with its id
hydra-ctl review            # answer them one by one
```

```text
  kind             open
  merges              0
  references          0
  placements          2
  stale               0
  contradictions      0
  verdicts            0
```

The demo asks only two placement questions. The merge and reference screens below come from adding a second collection that names the same man differently (`press.json`: "Jonathan Pollard", and a link that says only "Jonathan").

Each answer is saved at once to `.hydra/review/verdicts.yaml`, and the archive is rebuilt once at the end. `hydra-ctl review --only placements` asks just one kind.

## Keys

| Key | Does |
|---|---|
| a number | Picks that answer |
| `?` or Enter | Leaves the question open |
| `u` | Undoes the last answer |
| `q` | Stops |
| `a` | On a placement made by the position rules, keeps every placement that rule made |
| Tab / Shift+Tab | Rotates the view between all fields, fields in both, and conflicting fields |

## Merges

A merge asks whether two records are one entity or two. A merge with a conflict opens on just the conflicting fields, since that is what you have to decide. Here two records might be one man:

```text
[1/1] Merge
  Jonathan Pollard   and   Jonathan Jay Pollard

  pollard:per-k3m8v1qz5t   Person
     alias       Jay Pollard
     birthDate   1954
     name        Jonathan Pollard
     notes       Navy analyst, arrested in 1985

  pollard:per-w3v2f7z7pe   Person
     alias       Jonathan Pollard
     name        Jonathan Jay Pollard
     sources     pollard:doc-v9g25vcmkx
     weakAlias   Pollard

  [all fields]   fields in both   conflicting fields      Tab / Shift+Tab
Which is better?
  1  one entity
  2  two entities
  ? not sure   u undo   q quit
```

Press Tab to see every field of both records, with `=` for the same and `≠` for the conflict.

## References

A link written as a name that fits more than one record is asked as a reference. Here, which record does the Employment record mean by "Jonathan"?

```text
[1/1] Reference · a name with 2 possible records
  pollard:emp-b7d2n9x4hc   Employment.employee   Jonathan

  ┌─ Link from ───────────────────────────────┐
  │ pollard:emp-b7d2n9x4hc   Employment       │
  │  → employee   Jonathan                    │
  │    employer   Naval Investigative Service │
  │    role       analyst                     │
  └───────────────────────────────────────────┘

  1  pollard:per-k3m8v1qz5t   Person
     alias       Jay Pollard
     birthDate   1954
     name        Jonathan Pollard
     notes       Navy analyst, arrested in 1985

  2  pollard:per-w3v2f7z7pe   Person
     alias       Jonathan Pollard
     name        Jonathan Jay Pollard
     sources     pollard:doc-v9g25vcmkx
     weakAlias   Pollard

  [all fields]   name fields   matching fields      Tab / Shift+Tab
Which record is "Jonathan"?
  1  Jonathan Pollard       pollard:per-k3m8v1qz5t
  2  Jonathan Jay Pollard   pollard:per-w3v2f7z7pe
  3  neither
  ? not sure   u undo   q quit
```

## Placements

When the rules put a record under one parent and the data offers another, you pick the one the tree draws. Picking `a` keeps every placement made by the same rule.

```text
[1/2] Placement · Membership (several parents)
  Jonathan Jay Pollard
  …
Which is better?
  1  under Task Force 168                                pollard:org-ctk7r6bt77   now
  2  under Anti-Terrorist Alert Center                   pollard:org-8b2fsev104
  3  under Naval Ocean Surveillance Information Center   pollard:org-3kk63smvp7
  4  under Navy Field Operational Intelligence Office    pollard:org-1phejc0ngk
  ? not sure   u undo   q quit
```

Choosing an organization puts the record inside it. The position rules then decide who it sits under there, and never move it out of that organization.

The data in the entity's fields does not change. A placement only decides how the tree is drawn.

## Stale decisions and contradictions

A merge decision is saved with its evidence, so it comes back as stale if that evidence changes. A contradiction is a value the sources disagree on. Both are asked after the merges, references and placements.

## Leftover decisions

A decision whose question no longer exists (the records it was made on changed) is asked again, so you can drop it or keep it:

```text
[1/1] Decision problem
  verdicts.orphan: no ledger row has this key (the records it decided may have changed)
Which is better?
  1  remove that decision
  2  keep it                   now
  ? not sure   u undo   q quit
```

## Undoing decisions

`hydra-ctl answer <id> clear` clears one decision. [`reset`](../commands/review.md#reset) removes many at once, after backing up `verdicts.yaml`.

## The tree after review

After you reject Task Force 168 as his parent, the tree draws him under another and says why the first isn't the one:

```sh
hydra-ctl answer place-… reject
hydra-ctl tree pollard
```

```text
Jonathan Jay Pollard (Person) — Analyst
  also  Anti-Terrorist Alert Center                  Employment   analyst
  also  Navy Field Operational Intelligence Office   Employment   analyst
  also  Task Force 168                               Membership             rejected
Anne Henderson-Pollard (Person)
```

Each `also` line is another parent the record has. A word at the end says why it isn't the drawn one, such as `rejected` for a parent you turned down; see [`tree`](../commands/inspect.md#tree).
