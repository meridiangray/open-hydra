# Explore

These commands read the last build. None of them write anything.

## Searches

`tree`, `claims`, `sources` and `node find` understand the same kinds of word, in any order and any capitalisation:

| Word | Does | Example |
|---|---|---|
| A type, such as person, organization or company | Keeps that type and its subtypes (organization includes companies) | `hydra-ctl claims person anne` |
| A relationship (`tree` only): ownership, membership, employment, directorship, occupancy or family | Draws the chart along it | `hydra-ctl tree family employment` |
| `sources` | Adds the sources of what the command returned | `hydra-ctl claims pollard sources` |
| Anything else | The search, matched against names first and then other fields | `hydra-ctl node find pollard` |

Several search words make one search, so `claims jonathan jay` and `claims "jonathan jay"` are the same. A word may match the start of a name: `jon` finds Jonathan Jay Pollard.

| Option | Does |
|---|---|
| `--names` | Searches names and ids only |
| `--no-text` | Searches every field except free text (notes, descriptions) |

`search` in [`hydra.yaml`](../reference/config-files.md#hydrayaml) sets how far searches look when neither flag is given.

## check

```sh
hydra-ctl check
hydra-ctl check --format json
```

[See the output of each example](output.md#check)

Lists every problem in the archive's files (rules, params, records and decisions) as errors, warnings and infos, without building. It exits with status 1 when there is an error.

```text
  code                        level   found by   count   file
  direction.both-ends-above   info    check          1   .hydra/schema/direction.yaml

  code                        where       message
  direction.both-ends-above   Occupancy   both ends (holder, post) are in `above`; the target, post, is the parent

             check   old build
  errors         0           0
  warnings       0           0
  info           1           3
```

| Option | Does |
|---|---|
| `--format <text / json>` | Chooses how to print it (text by default) |

## details

```sh
hydra-ctl details
hydra-ctl details htest.hydra --format json
```

[See the output of each example](output.md#details)

One screen with the archive's name, when it was built, its collections and prefixes, records and entities by type, tree size, open questions and issues. It warns when files changed since the build, and never builds.

| Option | Does |
|---|---|
| `--format json` | Prints it as data |

## tree

```sh
hydra-ctl tree
hydra-ctl tree person
hydra-ctl tree "task force"
hydra-ctl tree family
hydra-ctl tree family employment
hydra-ctl tree organization sources
```

[See the output of each example](output.md#tree)

Draws every record once, under one parent, like an org chart. A record's other parents are listed under it, so nothing is hidden.

```text
Task Force 168 (PublicBody)
└── Jonathan Jay Pollard (Person) — Analyst
      also  Anti-Terrorist Alert Center                   Employment   analyst
      also  Naval Ocean Surveillance Information Center   Employment   research analyst
      also  Navy Field Operational Intelligence Office    Employment   analyst
```

When there is a reason the other parent isn't the drawn one, the line ends with it: `rejected` (you said no in review), `cycle` (it would make a loop) or `earlier` (its dates don't overlap the drawn one). With no word, both parents hold at once and the chart shows one.

| Command | Draws |
|---|---|
| `tree` | The whole chart |
| `tree person` | From each person not below another person |
| `tree "task force"` | From the records the search names |
| `tree family` | Only family links, and only the people in them |
| `tree family employment` | Both kinds, the first one a record has deciding its parent |
| `tree organization sources` | The chart, then the sources of everything drawn |

### Relationship charts

A relationship word draws only links of that kind. Every record at either end of one is drawn, each labelled with its link, and records with none are left out (the header counts them).

Records joined by these links are drawn together, with a blank line between unconnected groups, so one family reads as one block.

```text
Anne Henderson-Pollard (Person)
Jonathan Jay Pollard (Person)
  also  Anne Henderson-Pollard   Family   wife   sideways
```

For family, the relationship text decides the direction. It describes the relative from the person's side, so father, mother or parent puts the relative above the person, and son, daughter or child puts the person above the relative.

A child's line reads from the child's side ("child (father)" means the record says father). Anything else, such as spouse, sibling, uncle or in-law, stays sideways and is listed under the record's `person` on a "sideways" line.

Relationship charts only change what is displayed. Nothing is rebuilt or saved, and a parent you rejected or one that would make a loop is never used.

| Option | Does |
|---|---|
| `--read <declared / generic>` | Uses your hierarchy rules (declared, the default) or the generic ones only |
| `--stubs` | Also draws the names no record has where their links would put them, as if each were graduated (nothing is saved; see [`stubs`](review.md#stubs)) |
| `--format <text / json / mermaid>` | Chooses how to print it |
| `--ascii` | Uses plain ASCII lines instead of box drawing |
| `--vertical`, `--lateral`, `--direction`, `--singletons` | Mermaid only; see [below](#mermaid) |

### Mermaid

```sh
hydra-ctl tree --format mermaid > chart.mmd
hydra-ctl tree --format mermaid --vertical --direction LR
hydra-ctl tree family --format mermaid
```

`--format mermaid` prints the same chart as a Mermaid flowchart, which renders on GitHub, in mermaid.live and in most Markdown editors. Every way of choosing what to draw (a type, a search, a relationship, `--read`, `--stubs`) works the same.

| Line | Means |
|---|---|
| Solid arrow `-->` | The parent the record is drawn under, labelled with the role |
| Dotted arrow `-.->` | One of its other parents (the `also` lines), labelled with the role |
| Dotted line `-.-` | A sideways link, such as Associate or Family, labelled with its wording |
| `%% no links:` comment | The records left with no line, which Mermaid doesn't draw |

Labels come only from the records, never from your review choices.

#### Mermaid options

Mermaid lays out every line as if it went down, so sideways and other-parent lines pull records onto the wrong rows. On anything bigger than a small search, draw one kind of line at a time.

| Option | Draws | Use it for |
|---|---|---|
| `--vertical` | Only the solid lines | The hierarchy itself, the org chart |
| `--lateral` | Only the dotted lines | Who else each record is tied to |
| `--singletons` | Records with no line as boxes, instead of listing them in the `%% no links:` comment | Keeping every record on the chart after `--vertical` or `--lateral` drops its lines |
| `--direction LR` | Left to right instead of top-down (`TD`, the default) | Wide, shallow trees |

The options combine. Here is each one on the whole archive, `tree`:

=== "default"

    Both kinds of line. The dotted lines cross the hierarchy.

    ```mermaid
    --8<-- "tree-all-mermaid.txt:2:"
    ```

    [tree-all-mermaid.txt](../examples/tree-all-mermaid.txt)

=== "--vertical"

    Only who sits under whom.

    ```mermaid
    --8<-- "tree-all-mermaid-vertical.txt:2:"
    ```

    [tree-all-mermaid-vertical.txt](../examples/tree-all-mermaid-vertical.txt)

=== "--lateral"

    Only the other ties. Records with none are left out and named in the closing comment.

    ```mermaid
    --8<-- "tree-all-mermaid-lateral.txt:2:"
    ```

    [tree-all-mermaid-lateral.txt](../examples/tree-all-mermaid-lateral.txt)

=== "--lateral --singletons"

    The same, with those records drawn as boxes.

    ```mermaid
    --8<-- "tree-all-mermaid-singletons.txt:2:"
    ```

    [tree-all-mermaid-singletons.txt](../examples/tree-all-mermaid-singletons.txt)

=== "--direction LR"

    The default chart, laid out left to right.

    ```mermaid
    --8<-- "tree-all-mermaid-lr.txt:2:"
    ```

    [tree-all-mermaid-lr.txt](../examples/tree-all-mermaid-lr.txt)

`sources` can't be used with `--format mermaid`, because the source list would break the chart.

## positions

```sh
hydra-ctl positions
hydra-ctl positions --tree --nodes
hydra-ctl positions --unplaced
hydra-ctl positions --format mermaid
```

[See the output of each example](output.md#positions)

Draws the position ladder from the hierarchy rules: each position under the one above it, with the titles that count as it listed underneath. Then it lists the titles found in the data that no position takes, so you can see what the rules are missing.

```text
Analyst
  titles   analyst
           research analyst
  records  Jonathan Jay Pollard   Person
Associate   outside
  titles   associate
           close associate
           contact
Leader
│ titles   boss
│          leader
│          head of organization
```

`outside` marks a position that is off the ladder, `implied` one only the rules imply, and `^` a position met a second time. Problems in the rules, such as a position placed under one that isn't defined, are listed at the end.

`position` works as well. To change the ladder, see [Defining Hierarchies](../guides/hierarchy.md).

| Option | Does |
|---|---|
| `--tree` | Shows only the position tree |
| `--unplaced` | Shows only the titles no position takes |
| `--nodes` | Lists the records holding each position under it |
| `--read <declared / generic>` | Uses your hierarchy rules (declared, the default) or the generic ones only |
| `--format <text / json / mermaid>` | Chooses how to print it; mermaid draws the position graph |
| `--ascii` | Uses plain ASCII lines instead of box drawing |

## claims

```sh
hydra-ctl claims
hydra-ctl claims pollard
hydra-ctl claims person anne
hydra-ctl claims pollard sources --format json
```

[See the output of each example](output.md#claims)

Shows where each value of an entity came from, grouped by property, with the record and collection behind it and the source it cites. Values the sources disagree on are marked with `≠`.

Up to 10 entities are shown, best match first. A line "merged upstream from" lists ids an upstream tool merged into the entity.

```text
entity                 type     id                       claims   collections
Jonathan Jay Pollard   Person   pollard:per-w3v2f7z7pe        4             1

    field       value                    record                   collection
    alias       Jonathan Pollard         pollard:per-w3v2f7z7pe   pollard-damage-assessment
    name        Jonathan Jay Pollard     pollard:per-w3v2f7z7pe   pollard-damage-assessment
    sources     pollard:doc-v9g25vcmkx   pollard:per-w3v2f7z7pe   pollard-damage-assessment
    weakAlias   Pollard                  pollard:per-w3v2f7z7pe   pollard-damage-assessment

    …


```

Without a search, or as `claims summary`, it counts the claims behind the whole archive by collection, type and property. It also counts how many identity fields, such as a birth date, collections give differently (disputed).

```text
claims summary   Pollard case

  claims        156
  entities       45
  collections     2
  disputed        0

  collection                          claims      schema           claims      property       claims
  pollard-damage-assessment              146      PublicBody           38      name               25
  sources/pollard-damage-assessment       10      Person               32      sources            25
                                                  Employment           30      notes              14
  …
```

| Option | Does |
|---|---|
| `--type <type>` | Does the same as a type word |
| `--prop <property>` | Shows only that property |
| `--collection <name>` | Shows only claims from that collection |
| `--exact` | Makes a name or value have to equal the search |
| `--format <text / json>` | Chooses how to print it (text by default) |

## node find

```sh
hydra-ctl node find pollard
hydra-ctl node find person jay
hydra-ctl node find per-w3v2f7z7pe --field id
```

[See the output of each example](output.md#node-find)

Gives the records closest to a value, each with a score, and says which field matched.

```text
score   name                     schema   id                       position   parent           matched
1.00    Jonathan Jay Pollard     Person   pollard:per-w3v2f7z7pe   Analyst    Task Force 168   weakAlias  Pollard
0.93    Anne Henderson-Pollard   Person   pollard:per-jbcv7nwbwb
```

An equal name or identifier scores 1.00, a name holding all the words 0.90 or more, part of an id 0.85, another field equal to the value 0.80, and another field holding its words 0.75. Anything else is scored by how close it is to a name, so typos still find.

| Option | Does |
|---|---|
| `--field <any / name / id / identifier / value>` | Chooses where to look (`any` by default) |
| `--type <type>` | Does the same as a type word |
| `--limit <n>` | Shows at most that many (10 by default, 0 for all) |
| `--min <score>` | Hides anything lower (0.6 by default) |
| `--read <declared / generic>` | Chooses which read to search |
| `--format json` | Prints it as data |

## sources

```sh
hydra-ctl sources
hydra-ctl sources sella
hydra-ctl sources person --uncited
hydra-ctl sources damage
hydra-ctl sources --format json
```

[See the output of each example](output.md#sources)

Draws a tree per source, the source on top. Each source entry in `.hydra/sources/entries/` shows its type, publisher, id and link, with the entities that cite it underneath.

Each entity's line names the field that cites the source. It names the record too when the entity was merged from several records and the citation came from one of the others.

A document's pages sit under it, and whoever cites a page sits under that page. Documents that are part of the data, such as a case file and its pages, are listed apart from the source entries, and entities that cite nothing are counted.

In the demo, everything traces to one source entry, the damage assessment:

```text
  The Jonathan Jay Pollard Espionage Case: A Damage Assessment (Document)   Foreign Denial and Deception Analysis Committee, Director of Central Intelligence   pollard:doc-v9g25vcmkx
  └── Aviem Sella (Person)   sources   pollard:per-6q0b4zamfq
  …
```

| Command | Draws |
|---|---|
| `sources` | Every source |
| `sources sella` | Only the sources the entities the search names cite, with only those entities under them (names first, other fields only when no name matches) |
| `sources person` | The same for every person |
| `sources person --uncited` | The same, and also names each person citing nothing, so you can see what still needs a source |
| `sources damage` | Searches the sources themselves (id, title, publisher and link) when no entity matches, and draws each with everything citing it |

The word `sources` after `claims`, `node find` or `tree` draws the same for just what that command returned. [Sources](../concepts/sources.md) covers how they are stored.

| Option | Does |
|---|---|
| `--uncited` | Names each entity citing nothing, not just how many |
| `--format <text / json>` | Chooses how to print it (text by default) |
| `--ascii` | Uses plain ASCII lines instead of box drawing |
