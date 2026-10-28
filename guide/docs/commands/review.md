# Review and decide

These commands answer the questions a build leaves open, and save the answers in `.hydra/review/verdicts.yaml`. [Reviewing](../guides/reviewing.md) shows what each question looks like.

## todo

```sh
hydra-ctl todo
hydra-ctl todo --list
hydra-ctl todo --list placements
```

[See the output of each example](output.md#todo)

Counts the questions the last build left for a person, by kind. `--list` shows each question with the id that [`answer`](#answer) takes.

| Option | Does |
|---|---|
| `--list [kind]` | Lists the questions; with merges, references, placements, stale, contradictions or verdicts, only that kind |
| `--format json` | Prints it as data |

## review

```sh
hydra-ctl review
hydra-ctl review --only merges
```

[See the output of each example](output.md#review)

Asks the open questions one at a time. Each starts with what kind of question it is (Merge, Reference, Placement, Stale decision, Contradiction or Decision problem) and a detail such as the fields in conflict.

Then it asks "Which is better?" with the alternatives numbered and the current one marked "now". A merge with conflicting fields opens on just those fields; Tab shows the rest.

```text
[2/2] Placement · Membership (several parents)
  Aviem Sella
  …
Which is better?
  1  under Israeli Air Force     pollard:org-ez802bp11f   now
  2  under New York University   pollard:org-f8xs95cwk2
  ? not sure   u undo   q quit
```

Merges offer one entity or two, references the records a name could mean, and placements the parents a record could sit under. Stale decisions and contradictions come after.

Press a number to answer, `?` or Enter to leave it open, `u` to undo the last answer and `q` to stop. A placement made by the position rules also offers `a`, to keep every placement the same rule made.

Each answer is saved at once, and the archive is rebuilt once at the end.

| Option | Does |
|---|---|
| `--only <kind>` | Asks only merges, references, placements, stale, contradictions or verdicts |
| `--no-build` | Skips the rebuild at the end |

## answer

> You probably won't use `answer`. But an AI agent might.

```sh
hydra-ctl answer merge-3f2a… confirm
hydra-ctl answer place-17bd… reject
hydra-ctl answer ref-520d… 2
hydra-ctl answer cap-pollard:per-w3v2f7z7pe "Jonathan Pollard"
hydra-ctl answer place-17bd… clear
```

[See the output of each example](output.md#answer)

Records one decision, for scripts. The ids come from `todo --list`.

| Id | Takes |
|---|---|
| `merge-…` | confirm, reject or clear. It is saved with its evidence, so it comes back as stale if that changes |
| `place-…` | confirm, reject or clear |
| `ref-…` | A candidate number, a record id, none or clear |
| `cap-` and a record id | One of the entity's names (not an alias), or clear |

An entity has several names once records are merged. In the demo, with a press file added that calls him "Jonathan Pollard", confirming the two are one man makes `cap-pollard:per-w3v2f7z7pe "Jonathan Pollard"` valid.

| Option | Does |
|---|---|
| `--no-build` | Saves the decision without rebuilding |

## reset

```sh
hydra-ctl reset
hydra-ctl reset --only placements
```

[See the output of each example](output.md#reset)

Removes decisions from `.hydra/review/verdicts.yaml`. It says what will go, writes a backup beside the file, waits for Enter, then rebuilds.

To clear a single decision, use [`answer`](#answer) with clear.

| Option | Does |
|---|---|
| `--only <kind>` | Removes only merges, placements, references, captions or stubs |
| `--yes` | Doesn't wait for Enter |
| `--no-build` | Skips the rebuild |

## stubs

```sh
hydra-ctl stubs
hydra-ctl stubs graduate "Lakam"
hydra-ctl stubs graduate "Israeli Ministry of Defense" --as PublicBody
hydra-ctl stubs drop "Lakam"
```

[See the output of each example](output.md#stubs)

A stub is a name that link fields point at but no record has, such as an `owner` that names a company nobody wrote a record for. With no action, `stubs` lists each one: how many links name it, from which fields, and the most specific type all of those links can point at. Then it lists the names already graduated.

`graduate` turns a stub into one entity, so every link with that name points at it, and rebuilds. It takes the type the links fit unless `--as` names another.

`drop` undoes a graduation. Both are saved as decisions in `verdicts.yaml`, so `reset` removes them too.

To see where the stubs would land before graduating any, use `tree --stubs`.

| Option | Does |
|---|---|
| `--as <type>` | Graduates the name as that type |
| `--no-build` | Saves the decision without rebuilding |
| `--format json` | Prints the list as data |
