# Records and collections

Your `collections/` folder holds `.json` files, each one a collection. A file can be a JSON list of records or JSON lines, one record per line.

Hydra expects each record's `id` and `schema`, with its `properties`, the way FollowTheMoney writes them. Two records from the demo's `collections/heisenberg.json`:

```json
[
  {
    "id": "p-walt",
    "schema": "Person",
    "properties": {
      "name": [
        "Walter Hartwell White"
      ],
      "weakAlias": [
        "Walt",
        "Heisenberg",
        "Mr. Lambert"
      ],
      "birthDate": [
        "1958-09-07"
      ],
      "deathDate": [
        "2010-09-07"
      ],
      "sources": [
        "doc-bb-casefile~p1"
      ],
      "notes": [
        "chemistry teacher turned meth manufacturer — 'Heisenberg'"
      ]
    }
  },
  {
    "id": "rel-hb1",
    "schema": "Membership",
    "properties": {
      "member": [
        "Walter Hartwell White"
      ],
      "organization": [
        "Heisenberg Organization"
      ],
      "role": [
        "leader"
      ],
      "endDate": [
        "2010"
      ]
    }
  }
]
```

Everything in `collections/` is linked. You can copy a file in and run `build`, or use [`import`](../commands/setup.md#import), which checks that the file reads as records first.

## Ids

Every id is written as `<prefix>:<id>`, so records from different collections never collide. The prefix is the archive's, or one made from the collection's file name; `hydra-ctl collections` shows them, and the build stores them in `collections/manifest.json`.

The collection's name is its file name, so rename a file before you start reviewing. Afterwards, change its prefix with `hydra-ctl collections prefix`, so your decisions follow.

## Links

FollowTheMoney treats some fields as pointers to other entities via their id. Hydra uses natural field values as a container: the linked entity's name.

Here is the demo's Membership above as each export writes it. Both are JSON lines, one record per line, shown pretty-printed:

=== "FtM (`export --format ftm`)"

    ```json
    {
      "datasets": [
        "heisenberg"
      ],
      "id": "heisenberg:rel-hb1",
      "properties": {
        "endDate": [
          "2010"
        ],
        "member": [
          "heisenberg:p-walt"
        ],
        "organization": [
          "heisenberg:org-heisenberg"
        ],
        "role": [
          "leader"
        ]
      },
      "schema": "Membership"
    }
    ```

=== "Hydra (`export --format hydra-ftm`)"

    ```json
    {
      "datasets": [
        "heisenberg"
      ],
      "id": "heisenberg:rel-hb1",
      "properties": {
        "endDate": [
          "2010"
        ],
        "member": [
          "Walter Hartwell White"
        ],
        "organization": [
          "Heisenberg Organization"
        ],
        "role": [
          "leader"
        ]
      },
      "schema": "Membership"
    }
    ```

Both carry the prefixed id, and the collection as FtM's `datasets`. Only the links differ.

Hydra reads either form. An id is followed exactly and shown as the record's name, and the id is kept for export. A name that fits more than one record becomes a [reference question](../guides/reviewing.md#references) in review.

## FtM fields that carry over

FtM's `proof` is read as `sources`, and `export --format ftm` writes it back as `proof`. Upstream `referents` (ids another tool merged into a record) are kept, so the entity can be found by any of them.

## Stubs

A stub is a name that link fields point at but no record has, such as an `owner` that names a company nobody wrote a record for. [`stubs`](../commands/review.md#stubs) lists them and can graduate one into an entity.
