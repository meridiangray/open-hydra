# Pack and export

## pack, unpack

```sh
hydra-ctl pack
hydra-ctl pack htest -o case-one.hydra
hydra-ctl unpack case-one.hydra
```

[See the output of each example](output.md#pack) (and [unpack](output.md#unpack))

`pack` writes the archive as one `.hydra` file, a zip with a checksum for every file, including the last build. The same archive always gives the same bytes, and the parse cache is never included.

`unpack` checks every file and refuses paths that would leave the folder. `init` with a `.hydra` file does the same as `unpack`.

| Option | Does |
|---|---|
| `-o`, `--out <file>` | Chooses where to write the pack (the archive's name by default) |
| `--no-parsed` | Leaves the build out for a smaller file; it builds on first use |
| `--force` | Replaces an existing file |

## export

```sh
hydra-ctl export --format ftm
hydra-ctl export --format csv -o graph
hydra-ctl export case-one.hydra --format graphml
```

[See the output of each example](output.md#export)

Writes the archive for other tools, and reports what it wrote:

```text
Exported breakingbad as csv to breakingbad-graph
  entities   nodes   edges   unlinked relationships   ftm schema
       227     102     302                        1   65c772987032
```

| Format | Is |
|---|---|
| `ftm` | Standard FollowTheMoney JSON lines, for Aleph, OpenAleph and nomenklatura. Links hold record ids, sources are written as FtM's proof, and referents are kept |
| `hydra-ftm` | The same in Hydra's own form, with links as the names the records wrote. It can go back into a collection |
| `csv` | `nodes.csv` and `edges.csv` with `export.yaml`, for Kùzu, Neo4j and Gephi. Every relationship is an edge, plus the chart's chosen parent with its status |
| `graphml` | The same graph in one file, for Gephi, yEd and Cytoscape |

Every export is stamped with the FtM schema hash from `hydra.yaml`. [`import`](setup.md#import) reads all four formats back in.

| Option | Does |
|---|---|
| `--format <format>` | Chooses the format (required) |
| `-o`, `--out <path>` | Chooses where to write it (named after the archive, here, by default) |
| `--read <declared / generic>` | Chooses which read to export |
| `--force` | Replaces an existing output |
