# Laying out the wiki

`hydra-ctl wiki <archive> serve` shows an archive as a wiki with no setup. Everything about how it looks and what a
page contains can be changed in one file, `wiki.yaml`, in the archive folder. You never write HTML or JavaScript.

## What a page holds

A page gets *sections*: a few built in (offices, family, owners, timeline, and so on) and any you define. Anything a
page's records say that no section draws is listed anyway, under its relationship's own heading, so nothing is lost.

```sh
hydra-ctl wiki my-archive edges       # what the pages hold, and what draws each relationship
hydra-ctl wiki my-archive sections    # what is available, and what each page type gets
```

`edges` prints one line per page type, relationship and side, with a count and what draws it: `built-in`,
`defined: <name>` or `default list`. A `default list` line is a relationship you may want to lay out yourself.

## Define a section

```sh
hydra-ctl wiki my-archive define vessels_owned \
    --edge ownership --side source --other Vessel \
    --columns "Vessel=name,share,period,prop:tonnage" --sort former,-share \
    --title "Vessels owned" --for Person,Company
```

This writes to `wiki.yaml` (and adds the section to those page types, before "As recorded"). Nothing is written if the
definition is wrong; the error names the section and the key. `undefine NAME` takes it out again.

```yaml
define:
  vessels_owned:
    title: Vessels owned
    relations: {edge: ownership, side: source, other: Vessel}
    columns: [{label: Vessel, column: name}, share, period, {label: tonnage, prop: tonnage}]
    sort: [former, -share]
sections:
  Person: [lifebar, offices, family, vessels_owned, recorded]
```

| Key | Meaning |
|---|---|
| `relations.edge` | a role (`person`, `post`, `event`, `tenure`, `kin`, `ownership`, `representation`) or an edge name |
| `relations.side` | `source` or `target`: which end this page is |
| `relations.other` | only relationships whose other end is this type (or one that extends it) |
| `relations.verb`, `.former` | one verb or a list; `former: true` only ended ones, `false` only current ones |
| `columns` | `name`, `verb`, `share`, `status`, `period`, `date`, `deal`, `thumb` (the other end's picture), `badges`; `{label, column}` renames one; `{label, prop}` shows a property of the other end |
| `sort` | `former`, `share`, `period`, `name`; a leading `-` reverses |
| `view` | `table` (default), `list` or `timeline` |
| `min` | the fewest rows worth showing the section for |
| `props` | instead of `relations`: a table of this page's own properties |

A defined section also takes its relationship out of the default list on the pages that show it, so it is not drawn twice.

## Wording

The headings and opening sentences are generic by default. Each can be set in `wiki.yaml`:

```yaml
lead:                                  # a page's opening sentence, per schema (or a parent schema); false writes none
  Person: "{name} {life}: {offices}[; {kin} of {parents}]."
  Position: "{name}[, in {org}]: held by {holders} people[; latest {latest}]."
  PublicBody: false
edge_labels:                           # the heading a relationship's list gets, by edge and by which end the page is
  Membership: {source: Memberships held, target: Members}
  Directorship: {source: Directorships, target: Directors}
field_labels:                          # the heading in "Mentioned in", by the field that names the page
  Organization: Positions in it
```

A template's `{slot}` is replaced by what the records say, and `[ ... ]` is dropped when a slot inside it is empty.
Slots: for a person `name life was demonym offices office_count more parents kin`; for a position
`name org holders since latest latest_from`; for a body `name kind country posts`. An unknown slot is an error when
the wiki loads. With no `lead:` entry the built-in sentence is used.

## If your schema names things differently

The built-in sections look for `Person`, `Position`, `Occupancy` (a person holding a post), `Family`, `Ownership` and
`Representation`. If your archive calls them something else, say so once:

```yaml
roles:
  person: Human
  tenure: Appointment
  ownership: Holding
```

## Pictures, icons and badges

Images and badges come from `hints.yaml` ([Images and badges](hints.md)); the wiki uses them without any setup. A page's
infobox leads with a portrait for a person and a logo for anything else, and a page with several images gets
previous and next buttons to step through them. A small picture beside a name (a table row) prefers a thumb.

Each page type has an icon, from its own type or the nearest type it extends (a vessel takes its asset's). To give a
type another one, name a file under `.hydra/resources/icons/`:

```yaml
icons:
  Case: gavel          # gavel.svg in the archive's own icons folder
badges:
  crown: Head of house # how a hint badge is worded; null hides it
```

### Derived badges

A person's page also earns badges from what their records say, with no rule per person: *In office* (a post with no end
date and no recorded death), *King*, *Crown prince*, *Governor*, *Minister*, *Ambassador*, *Military*, a service branch
(*Air force*, *National Guard*, *Land forces*, *Navy*) and an industry (*Energy*, *Finance*, *Media*, *Sport*,
*Business*, ...). Each is a regular expression over a post's title or an occupation:

```sh
hydra-ctl wiki my-archive badges        # every rule, and how many pages it reaches
```

```yaml
badge_rules:
  judge: {label: Judge, group: role, icon: shield, tip: Sat as a judge, title: '\bjudge\b'}
  sport: null                       # drop a built-in rule
  governor: {label: Governor of a province}
  energy: {title: 'petroleum|\boil\b|energy|mineral|acme oil'}   # widen a rule with your archive's own names
derived_badges: {max: 6}            # or false to switch them all off
```

Write a `title` in single quotes. In double quotes YAML reads `\b` as a backspace, so the rule quietly matches
nothing, and it refuses `\s` outright.

The built-in rules use general words only (*petroleum*, *national guard*, *football*). They name no particular
company, club or agency, so an archive adds its own by restating the rule's `title`, as `energy` does above.

`group` is `role` (a post takes the first role rule that fits), `service` or `industry`. `icon` is a file under
`.hydra/resources/icons/`. To give one entity a badge by hand instead:
`hydra-ctl hints set badge crown --titled "^King"`.

## Page layout and the wiki's own pages

```yaml
layout: column          # float (default): the infobox floats beside the text; column: it keeps a column of its own
flags: circle           # circle (default), rect, square or none: the flag drawn beside a country
navboxes: true          # the boxes of related entries at the foot of a page
landing: [explore, featured, in_office, years_ago, added, people]   # the main page's sections, in order (this is the default)
actions_draft: true     # three sample buttons in each page's actions box, to see the box; they do nothing yet
```

Besides the entries, the live wiki (`hydra-ctl wiki my-archive serve`) has these pages:

| Page | What it shows |
|---|---|
| `/collections` | Every collection, with its records and what they cite |
| `/sources` | How the records are sourced, per collection: Wikipedia only, other sources, no source |
| `/review` | The open questions of the last build (merges, references, placements) as cards. Read only: answer them with `hydra-ctl review` or `answer` |
| `/maintenance` | Pages with cleanup banners: no sources, contradicting facts |
| `/changes` | What each recorded change did, from the archive's history |
| `/settings` | The settings above, as this wiki reads them |

The static site (`hydra-ctl wiki my-archive site`) writes the entries, categories, name and year pages and search.
It has no `/review`, `/changes`, `/sources`, `/collections` or flags, since those need the live server.

Flags come from the [circle-flags](https://github.com/HatScripts/circle-flags) and
[flag-icons](https://github.com/lipis/flag-icons) libraries, found in a `vendor/` folder above hydra's code or in
`$HYDRA_FLAGS_DIR`. A style whose library is missing draws no flag.

`hydra-ctl wiki my-archive check` reports hint rules that reached no entity (`hints.unmatched`) and page types with
no icon (`icons.missing`).

## Looks

```yaml
theme:
  base: dune                  # shore | dune | tide | tan | light
  fonts: {heading: "Georgia, serif", body: "system-ui, sans-serif"}
  radius: 12px
about: One sentence for the front page.
```

## Editing by hand

`define`, `undefine` rewrite `wiki.yaml` whole, so a file with comments is refused unless you add `--force` (the old
file is kept as `wiki.yaml.bak`). Edit it by hand to keep comments; a mistake in a definition is reported when the wiki
loads.
