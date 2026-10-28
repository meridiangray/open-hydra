# Sources

`.hydra/sources/entries/` holds the material your data comes from: one record per source, usually an FtM `Article` or `Document` with a title, publisher and link. The demo's one entry, with some fields left out (its id is made from the file's `contentHash`, so one file is one id wherever it is added). Each file is a JSON list, like a collection:

```json
[
  {
    "id": "doc-v9g25vcmkx",
    "schema": "Document",
    "properties": {
      "title": [
        "The Jonathan Jay Pollard Espionage Case: A Damage Assessment"
      ],
      "publisher": [
        "Foreign Denial and Deception Analysis Committee, Director of Central Intelligence"
      ],
      "publishedAt": [
        "1987-10-30"
      ],
      "fileName": [
        "2007-010-doc1.pdf"
      ],
      "mimeType": [
        "application/pdf"
      ],
      "contentHash": [
        "e5acaf72330a527a867c71615f220e61cb4f148e"
      ]
    }
  }
]
```

A record cites its sources by id in its `sources` field. The link lives once, on the source entry, never repeated on the records.

Relationships (Ownership, Membership and the like) cite nothing; the entities they join carry the sources.

## Two kinds of document

A **source entry** is where content came from: a Wikipedia page, a news article. It belongs in `.hydra/sources/entries/`.

A **document in the data** is part of the content itself: a case file and its pages that the investigation is about. It belongs in a collection, like any other record.

Neither appears as a box in the tree; both show up as evidence on the records that cite them.

## Looking at sources

`hydra-ctl sources` draws what cites what, and the word `sources` after `claims`, `node find` or `tree` lists the sources behind just that result:

```sh
hydra-ctl sources sella
```

```text
sources

  entities   1

  entries

  The Jonathan Jay Pollard Espionage Case: A Damage Assessment (Document)   Foreign Denial and Deception Analysis Committee, Director of Central Intelligence   pollard:doc-v9g25vcmkx
  └── Aviem Sella (Person)   sources   pollard:per-6q0b4zamfq

  uncited    0
```

## Sourcing one value at a time

A source in FtM is cited by a whole record, not by one of its fields, so Hydra can say which record cites a source but not which value the source supports.

To source values one by one, write one record per source with only what that source says. The build merges them, and `claims` then traces each value to its own record and source.
