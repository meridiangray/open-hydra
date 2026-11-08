# Reading Wikidata into an archive

`hydra-ctl wikidata import` fetches Wikidata items and writes them as a collection, each fact in the field it
belongs to. Which Wikidata property fills which field is one file you can edit, `.hydra/rules/wikidata.yaml`.

```sh
hydra-ctl wikidata import my-archive Q937 Q42 Q95
```

```text
Imported 3 Wikidata items as 136 records

COPIED INTO FIELDS  91  a Wikidata claim became a value in a Hydra field
  Field               Times  Wikidata property             Example
  Person.birthDate        2  P569 date of birth            Albert Einstein: 1879-03-14
  Person.citizenship      5  P27 country of citizenship    Albert Einstein: ch
  …
MADE INTO RECORDS  74  a claim between two things became a record of its own
  Family                  4  P26 spouse                    Albert Einstein → Mileva Marić
  …
```

## What an import makes

- **A record per item**, with its name, aliases, short description (`summary`) and its key,
  `upstream: wikidata:Q937`. A record anywhere in the archive that holds the same key joins it as one entity.
- **A field value per claim the map names.** The field's type decides how the value is read: a date keeps its
  precision (a decade becomes its first year, marked approximate), a country becomes its lower-case ISO code, a
  language its ISO 639-3 code, anything else its English label or text. A claim with no usable value is counted
  under *Left out*, never guessed.
- **A record per relationship claim** (spouse, child, member of, employer…), with the claim's start and end dates,
  and a stub for the item at the other end that carries only its name and key.

Deprecated claims are never read, and when a property has preferred claims only those are.

## Finding what the map misses

An item carries hundreds of claims and the map reads a few. `unread` lists the rest:

```sh
hydra-ctl wikidata unread Q937 Q42 Q95
hydra-ctl wikidata prop P2048          # what a code means
```

It groups them as properties that could fill a Hydra field (with the field), ids on other sites (keys, not
fields) and the rest, most common first. To read one, add `P2048: height` under its type in `wikidata.yaml`;
to stop seeing one, add its code to `ignore:`. The suggestions come from the field's type and a word shared with
the property's name, so they are prompts to check, not answers.

## The file

`.hydra/rules/wikidata.yaml` (your archive's own copy replaces the one hydra ships) has `classes` (which
Wikidata class is which schema), `properties` (code → field, per schema), `relationships` (a claim → a record),
`common` and `ignore`. Its header explains each. Answers from Wikidata are cached in `.hydra/cache/wikidata/`.
