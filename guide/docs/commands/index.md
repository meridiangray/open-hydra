# Command reference

Every command is `hydra-ctl <command> [<dir>] [options]`. Leave out `<dir>` and the command uses the active archive (see [`activate`](setup.md#activate-deactivate)) or the current folder.

Run `hydra-ctl` alone for the list, or `hydra-ctl <command> --help` for one command's options.

```sh
hydra-ctl details                         # one-screen summary
hydra-ctl tree                            # the org chart
hydra-ctl tree "task force"                # start at a search
hydra-ctl positions                       # the position ladder and titles nothing takes
hydra-ctl claims "Jonathan Jay Pollard"  # read the claims for "Jonathan Jay Pollard"
hydra-ctl sources                         # which documents cite what
hydra-ctl hints                           # image and badge rules, with hit counts
hydra-ctl check                           # problems in the files
hydra-ctl todo                            # open questions
hydra-ctl review                          # answer them one by one
```

## Commands and what they write

| Command | Does | Writes |
|---|---|---|
| [`init`](setup.md#init) | Creates an archive, or opens a `.hydra` file into one | The new folder |
| [`activate`, `deactivate`](setup.md#activate-deactivate) | Set the archive to use when none is given | `.hydra-activate` in this folder |
| [`import`](setup.md#import) | Loads FtM JSON (standard or Hydra's), or a CSV or GraphML export, as a collection | The collection file, then rebuilds |
| [`build`](setup.md#build) | Compiles the collections and sources into a build | `.hydra/parsed/` and `collections/manifest.json` |
| [`check`](inspect.md#check) | Lists the problems in the archive's files, without building | Nothing |
| [`details`](inspect.md#details) | One screen of records, types, tree size and open questions | Nothing |
| [`tree`](inspect.md#tree) | Draws the record tree, from a type, a relationship or a search | Nothing |
| [`positions`](inspect.md#positions) | Draws the position tree and the titles no position takes | Nothing |
| [`claims`](inspect.md#claims) | Shows where each value of an entity came from | Nothing |
| [`node find`](inspect.md#node-find) | Lists the records closest to a value | Nothing |
| [`sources`](inspect.md#sources) | Lists the sources, and which entities cite each | Nothing |
| [`todo`](review.md#todo) | Counts what the last build needs a person to decide | Nothing |
| [`review`](review.md#review) | Asks the open questions one by one | `verdicts.yaml`, then rebuilds |
| [`answer`](review.md#answer) | Records one decision, for scripts | `verdicts.yaml`, then rebuilds |
| [`reset`](review.md#reset) | Removes decisions, after backing them up | `verdicts.yaml` and a backup, then rebuilds |
| [`stubs`](review.md#stubs) | Lists names that links point at but no record has, and graduates one | `verdicts.yaml`, then rebuilds |
| [`pack`, `unpack`](share.md#pack-unpack) | Turn an archive into one `.hydra` file, and back | The `.hydra` file, or the folder |
| [`export`](share.md#export) | Writes the archive for other tools | The output file or folder |
| [`collections`](settings.md#collections) | Lists collections and their id prefixes, and changes one | `collections/manifest.json`, then rebuilds |
| [`defaults`](settings.md#defaults) | Checks, switches off or restores the default config files | `hydra.yaml`, or the restored files |
| [`hints`](settings.md#hints) | Lists the image and badge rules, and links an image file by one | `.hydra/resources/` and `hints.yaml`, then rebuilds |
