# Hydra Archives

Hydra uses its own archive format to hold everything needed to merge records, build hierarchies and link sources and media to entities: the data, the rules that shape it, and the decisions made while reviewing it.

!!! warning
    Everything here is in alpha and will very likely change, including where things are installed. Hydra will not drift from its principle: a modifiable, portable configuration travels with the data, with defaults provided and methods kept consistent.

An archive is a folder. `hydra-ctl init <folder>` creates one there from the built-in template.

```
case/
├── hydra.yaml                      the archive's name, id prefix and FtM schema hash
├── collections/                    your records
├── session/                        incoming data (not built yet)
└── .hydra/                         managed by hydra
    ├── sources/entries/            the sources your records cite
    ├── rules/                      positions and media rules
    ├── review/                     your review decisions (verdicts.yaml)
    ├── schema/                     the FollowTheMoney schema, params, direction and extension types
    ├── resources/                  icons and media
    ├── parsed/                     the last build
    └── cache/                      parsed config kept between runs
```

[Records and collections](records.md) and [Sources](sources.md) cover the data. [Config files](../reference/config-files.md) covers `hydra.yaml`, the rules and the schema.

## session/

`session/` is an API surface for agents to deliver raw `.json` data for rapid ingestion. It is a **highly volatile** feature, and nothing in it is built until it is moved into `collections/`.

## resources/

`.hydra/resources/` contains the icon and image media that hints point at. It can also act as a blob store for the source files that entities and relationships are derived from.

This is **highly volatile**, and will soon change to use a portable S3 container instead of git LFS.

## Defaults

Hydra ships generic defaults for the rule and schema files. Only change these if you want to set your own custom hierarchy; [`defaults`](../commands/settings.md#defaults) shows which ones you have changed and restores them.

## The .hydra file

`hydra-ctl pack` turns an archive into one portable `.hydra` file: a zip of everything above, with a checksum for every file and the last build included. The same archive always packs to the same bytes, and the cache is left out.

`hydra-ctl init case.hydra` opens one into a folder. Commands that only read take the file directly.
