# Setup and build

## init

```sh
hydra-ctl init htest
hydra-ctl init htest --name "Breaking Bad" --prefix bb
hydra-ctl init htest.hydra
```

[See the output of each example](output.md#init)

Creates an archive in a new or empty folder from the built-in template, or opens a `.hydra` file into one.

At a terminal it asks for the archive's name (Enter keeps the folder's name) and its id prefix (Enter takes one made from the name, and `none` keeps a prefix per collection).

| Option | Does |
|---|---|
| `--name <name>` | Sets the archive's name without asking |
| `--prefix <prefix>` | Sets the archive's id prefix without asking |

## activate, deactivate

```sh
hydra-ctl activate htest
hydra-ctl activate
hydra-ctl deactivate
```

[See the output of each example](output.md#activate)

`activate` with a folder writes `.hydra-activate` here, and commands run from this folder (or below it) then use that archive. Without a folder it shows the active archive.

`deactivate` removes the marker.

## import

```sh
hydra-ctl import ~/exports/opensanctions.json --format ftm
hydra-ctl import case.hydra-ftm.jsonl --format hydra-ftm --name fring
hydra-ctl import case-graph --format csv
hydra-ctl import case.graphml --format graphml --force
```

[See the output of each example](output.md#import)

Loads records into the archive as a collection, from the same formats `export` writes. Copying a file into `collections/` yourself and running `build` does the same for `ftm` and `hydra-ftm`; `import` checks the file reads as records first, names the collection and rebuilds.

| Format | Is |
|---|---|
| `ftm` | Standard FollowTheMoney JSON: a list, `{"entities": [...]}`, or JSON lines, as Aleph, OpenSanctions and other FtM tools write it. FtM's `proof` is read as `sources` |
| `hydra-ftm` | The same with links written as names, as `export --format hydra-ftm` writes it |
| `csv` | The folder `export --format csv` writes (`nodes.csv` and `edges.csv`) |
| `graphml` | The file `export --format graphml` writes |

A graph carries each entity's id, type and name, and its links. Each relationship edge becomes the relationship (with its role and dates), and each link-property edge the property.

Other fields are not in a graph, so they don't come back. The tree and open merges (`placedUnder`, `sameAs`) are left out too; a build works them out again.

`ftm` and `hydra-ftm` files are copied as they are, and a graph is written as FtM JSON lines. The collection takes the file's name (`case.ftm.jsonl` becomes `case`, `case-graph/` becomes `case`).

| Option | Does |
|---|---|
| `--format <format>` | Says what the file is: `ftm`, `hydra-ftm`, `csv` or `graphml` |
| `--name <name>` | Chooses the collection's name |
| `--force` | Replaces a collection of that name |
| `--no-build` | Imports without rebuilding |

## build

```sh
hydra-ctl build
hydra-ctl build htest --force
```

[See the output of each example](output.md#build)

Reads every file in `collections/` and `.hydra/sources/entries/`, merges records that are the same entity, places them, and writes `.hydra/parsed/`. It prints a summary of records, claims, nodes, merges, placements and references by status, and issue counts.

When nothing has changed since the last build, it prints that summary again without building.

Standard FtM data works as it comes. A link field that holds a record's id (as in `owner: ["NK-p1"]`) is followed by that id and shown as the record's name, and the id is kept for export.

| Option | Does |
|---|---|
| `--force` | Builds even when nothing changed |
| `--no-prefix` | Keeps record ids as written, without prefixes |
| `--verbose` | Also prints the full summary: claims, reads and the review ledger |
