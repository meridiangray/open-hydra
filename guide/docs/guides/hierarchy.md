# Defining Hierarchies

This guide is for anyone writing `.hydra/rules/positions.yaml` from scratch, whether a person or an agent working on their behalf. The defaults Hydra ships are deliberately small. Most investigations need their own ladder of ranks, and this is how to build one that Hydra reads the way you mean it.

## How Hydra builds a tree

Hydra places every record in two steps.

1. **The records decide which organization.** A Membership, Employment, Directorship or Ownership record links two entities, and `direction.yaml` says which end is the parent: the organization above its member, the employer above its employee, the owner above what it owns. When the records give a record several possible parents, review asks you to choose.
2. **Positions rank people inside an organization.** Once a record is inside an organization, the position rules decide who it sits under there: a Soldier under the Lieutenant, a Lieutenant under the Underboss. This is what `positions.yaml` controls.

The position rules only work inside organizations. They never decide which organization someone belongs to, and once you confirm an organization for someone in review, they never move them out of it.

## Where a record's title comes from

The rules rank a record by its title. Hydra takes the first of these that matches a position:

1. the `role` on the relationship that places it (its Membership, Employment, Directorship…)
2. the `role` on its other relationships
3. its own `position` field

A title matches a position when it equals the position's name or one of its `titles`, whole. Case and accents don't matter, and punctuation counts as a space:

| Role in the record | Matches the title | Why |
|---|---|---|
| `Vice-President` | `vice president` | the hyphen counts as a space |
| `Vice Président` | `vice president` | accents are ignored |
| `VP` | `vp` | case is ignored |
| `V.P.` | `v.p.` only | the dots become spaces: "v p" |
| `VP of Sales` | `vp of sales` only | the whole role must match |

A record with no role and no `position` gets no title, so the rules leave it directly under its organization. Hydra never ranks anyone by a title the data doesn't contain.

(`direction.yaml` can opt in to filling a blank role with `edge_positions`, but that is off by default for this reason.)

## The format

Each position is one line:

```yaml
Position name: {below: [Rank above], titles: [other words for it]}
```

`titles`
:   The position's aliases: every wording your data uses for it. The position's own name counts as a title too.

`below`
:   The rank directly above. A record goes under the nearest member of its organization who holds that rank, and if nobody does, under the rank above that.

`above`
:   The same link written from the other side: `Underboss: {above: [Lieutenant]}` means Lieutenant is below Underboss. Use one or the other, not both, for the same link.

`outside: true`
:   A position beside the organization rather than in it, such as a lawyer or an associate. Outside positions never rank anyone and are never ranked.

## defaults/positions.yaml and positions.yaml

`defaults/positions.yaml` ships with four positions about an organization's own leadership. `positions.yaml` is yours and ships empty.

```yaml
positions:
  Leader:            {titles: [boss, leader, head of organization]}
  Second-in-command: {below: [Leader], titles: [second in command, deputy]}
  Member:            {below: [Second-in-command, Leader], titles: [member, crew member]}
  Associate:         {outside: true, titles: [associate, close associate, contact]}
```

A position you name in `positions.yaml` that also exists in the defaults keeps its generic titles and adds yours. It keeps its generic place in the ladder too, unless your entry gives its own `below` or `above`, which then replace the generic ones.

So mapping your data's wording onto a default rank is one line, and nothing moves: `Leader: {titles: [administrator, chair]}` makes "administrator" and "chair" rank as Leader. Keep the wording in the records as the source has it; the title does the mapping.

A new name in `positions.yaml` simply adds a position, and it can sit under a generic one (`below: [Leader]`). The demo archive, for instance, moves Member down a level:

```yaml
Member: {below: [Crew chief, Head of security, Second-in-command]}
```

To start from nothing, switch the generic positions off with `hydra-ctl defaults off generic`, and `positions.yaml` is the whole ladder. The shipped `hints.yaml` still gives icons to Leader and Second-in-command, so `check` warns `hints.unknown-position` until you point those two rules at your own ranks (`match: {position: Boss}`) or remove them.

## Labelling strategies

If your data's roles don't line up with the hierarchy, you have a few options:

1. Label your positions using existing labels in the hierarchy.
2. Modify the hierarchy to fit your data.
3. Add the wording your data uses as a title on an existing position.

It's reasonable to gather some data first, then shape `positions.yaml` after.

## Step by step

1. **Build once and look at the titles your data uses.**
   ```sh
   hydra-ctl build
   hydra-ctl positions --unplaced
   ```
   This lists every role and position wording found in the data that no position takes yet. These are your raw material.
2. **Sketch the ladder top down.** One name per rank, then, for each rank, the wordings from step 1 that mean it.
3. **Write `positions.yaml`.** In each `below`, name only the rank directly above.
4. **Check the files.**
   ```sh
   hydra-ctl check
   ```
   It reports a title claimed by two positions (`positions.title-twice`; the first position wins), a misspelled key, or an outside position with a `below`.
5. **Build and read the ladder.**
   ```sh
   hydra-ctl build
   hydra-ctl positions --tree --nodes
   ```
   The ladder shows each position, its titles and who holds it. Problems the ladder itself has are listed at the end under `issues`: a position named in a `below` that you never defined, or a loop (A below B, B below A), which Hydra cuts.
6. **Look at the tree.**
   ```sh
   hydra-ctl tree
   hydra-ctl positions --unplaced
   ```
   Each record now sits under its rank. Anything still listed by `--unplaced` is a wording you haven't given a position, which may be fine (not every role is a rank) or an alias to add.
7. **Review the placements.** `hydra-ctl review --only placements` asks about each placement the rules made. `a` keeps every placement one rule made at once, a number picks another parent, and your answers stay through later builds.

Repeat steps 3 to 7 as the data grows.

## Rules that keep a hierarchy valid

**Name one rank in `below`.**
:   `Staff: {below: [Vice president]}` falls back to the chief executive on its own when there is no vice president. `Staff: {below: [Vice president, Chief executive]}` puts both on the same level, and the first in alphabetical order wins: staff end up under the chief executive.

**Give each title to one position.**
:   If two positions claim "director", the first wins and `check` warns.

**Define every position you name.**
:   A `below` that names an undefined position creates an empty "implied" one and an issue.

**No loops.**
:   If A is below B and B below A, Hydra cuts one link and reports it.

**Keep separate chains separate.**
:   A company and a criminal crew need different rank names and titles. Ranks with the same name are one rank everywhere in the archive.

**Watch organization memberships.**
:   An organization whose Membership role is a position title is ranked like a person: a unit that is a "member" of an agency goes under the agency's Leader. For one organization inside another, use a role that is not a rank, such as "affiliate", "unit" or "branch", or leave the role blank.

**Add other languages as aliases.**
:   `titles: [boss, jefe, capo]`. Accents are already ignored, so `líder` matches `lider`.

**Quote values with commas, colons or `#`.**
:   Inside `{…}`, write `titles: ["head, operations"]`, or YAML splits the value.

**Icons go elsewhere.**
:   `positions.yaml` only holds positions. Icons and badges by position go in [`hints.yaml`](hints.md) (`match: {position: Lieutenant}`).

## Recipes

Each of these has been built and checked with Hydra. None is on by default. To use one, paste its block below at the end of `.hydra/rules/positions.yaml` (the shipped file holds only comments), add your data's wordings to the titles, then run `hydra-ctl check` and `hydra-ctl build`.

### A criminal organization

Its titles overlap the generic positions, so switch those off first: `hydra-ctl defaults off generic`

```yaml
Boss:        {titles: [boss, leader, don, kingpin]}
Underboss:   {below: [Boss], titles: [underboss, second in command]}
Lieutenant:  {below: [Underboss], titles: [lieutenant, capo, captain]}
Soldier:     {below: [Lieutenant], titles: [soldier, enforcer, crew member]}
Lawyer:      {outside: true, titles: [lawyer, attorney, consigliere]}
```

### A company

Kept apart from the generic Leader chain:

```yaml
Chief executive: {titles: [ceo, chief executive officer, president, managing director]}
Vice president:  {below: [Chief executive], titles: [vice president, vp, v.p., senior vice president]}
Staff:           {below: [Vice president], titles: [staff, analyst, engineer, manager]}
Board member:    {outside: true, titles: [director, board member, chairman]}
```

The board sits beside the chain, so board members never rank staff, and staff never rank under a director. The defaults leave corporate ranks out on purpose: one shared ladder for every kind of relationship put employees under board members and companies under people.

### A government agency

```yaml
Agency director:          {titles: [director, administrator, commissioner]}
Deputy director:          {below: [Agency director], titles: [deputy director, deputy administrator]}
Special agent in charge:  {below: [Deputy director], titles: [special agent in charge, sac, field office head]}
Special agent:            {below: [Special agent in charge], titles: [special agent, agent, investigator]}
```

With records whose roles say "Administrator", "Deputy Administrator", "SAC" and "special agent", this draws (the `also` lines left out):

```
Federal Drug Agency (PublicBody)
└── Dana Hale (Person) — Agency director
    └── Rob Kerr (Person) — Deputy director
        └── Lia Ortiz (Person) — Special agent in charge
            └── Sam Webb (Person) — Special agent
```

A fifth role in the same data, "Task Force Officer", shows up in `positions --unplaced` until you give it a position.

The company and agency recipes both use "director" for different ranks. In one archive, pick one meaning per title.

## For agents

An agent building a hierarchy should follow the steps above, reading Hydra's own output instead of guessing:

- **Read the titles in use:** `hydra-ctl positions --unplaced --format json` returns `{"unrelated": [...], "issues": [...]}`. Only give positions to wordings that appear there. Never invent titles the data doesn't use.
- **Read the current ladder:** `hydra-ctl positions --format json`.
- **Write only `positions.yaml`.** Leave `defaults/positions.yaml` and `direction.yaml` as shipped unless the person asks.
- **Validate before finishing:** `hydra-ctl check` must show no errors and no `positions.*` or `hints.unknown-position` warnings, and after `hydra-ctl build`, `hydra-ctl positions --format json` must return `"issues": []`.
- **Leave the decisions to the person.** Don't answer review questions on their behalf. A hierarchy proposes placements, and the person confirms them.
