# Reviewing

Hydra assumes your fields are correct, then asks you about what it can't settle itself: records that might be one entity, names that could mean several records, and records with more than one possible parent.

```sh
hydra-ctl todo              # count what is open, by kind
hydra-ctl todo --list       # each question with its id
hydra-ctl review            # answer them one by one
```

```text
  kind             open
  merges             14
  references          3
  placements         47
  stale               0
  contradictions      0
  verdicts            1
```

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

A merge asks whether two records are one entity or two. A merge with a conflict opens on the conflicting fields, since that is what you have to decide:

```text
[2/7] Merge · conflicting: date
  To'hajiilee shootout   and   Junkyard shootout — Tuco Salamanca killed

  operations:ev-tohajiilee   Event
     date        2010

  operations:ev-tuco   Event
     date      ≠ 2008

  all fields   fields in both   [conflicting fields]      Tab / Shift+Tab
Which is better?
  1  one entity
  2  two entities
  ? not sure   u undo   q quit
```

Press Tab to see every field of both records, with `=` for the same and `≠` for the conflict.

## References

A link written as a name that fits more than one record is asked as a reference. Here, which record does the Documentation record mean by "Heisenberg"?

```text
[1/3] Reference · a name with 3 possible records
  dea:prv-dea1   Documentation.entity   Heisenberg

  ┌─ Link from ─────────────────────────────────┐
  │ dea:prv-dea1   Documentation                │
  │    document   heisenberg:doc-bb-casefile~p1 │
  │  → entity     Heisenberg                    │
  └─────────────────────────────────────────────┘

  1  dea:p-heisenberg-dea   Person
     name            = Heisenberg
     …

  2  heisenberg:p-walt   Person
     name              Walter Hartwell White
     …

  3  heisenberg:org-heisenberg   Organization
     name              Heisenberg Organization
     …

Which record is "Heisenberg"?
  1  Heisenberg                dea:p-heisenberg-dea
  2  Walter Hartwell White     heisenberg:p-walt
  3  Heisenberg Organization   heisenberg:org-heisenberg
  4  none of these
  ? not sure   u undo   q quit
```

## Placements

When the rules put a record under one parent and the data offers another, you pick the one the tree draws. Picking `a` keeps every placement made by the same rule.

```text
[5/47] Placement · rules: Member below Leader
  Huell Babineaux
  …
Which is better?
  1  under Walter Hartwell White     heisenberg:p-walt   now
  2  under Heisenberg Organization   heisenberg:org-heisenberg
  a  keep all 13 placed by rules: Member below Leader
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

```sh
hydra-ctl tree "Heisenberg Organization"
```

```text
Heisenberg Organization (Organization)
├── Walter Hartwell White (Person) — Leader
│   │ also  Dead freight methylamine heist     ProjectParticipant   planner
│   │ also  Gustavo Fring Organization         Membership           cook
│   ├── Brandon Mayhew (Person) — Distributor
│   │     also  Pinkman street crew   Membership   dealer
│   …
```

Each `also` line is another parent the record has. A word at the end says why it isn't the drawn one, such as `rejected` for a parent you turned down; see [`tree`](../commands/inspect.md#tree).
