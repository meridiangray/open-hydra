# Settings

## collections

```sh
hydra-ctl collections
hydra-ctl collections prefix press media
hydra-ctl collections prefix press media --rekey
```

[See the output of each example](output.md#collections)

Lists each collection (one per file in `collections/`) with its id prefix, and whether that prefix is the archive's, set in the manifest, or made from the file name.

```text
  prefixes set in   archive

  collection                  prefix    records   own prefix   claims   in others   citations
  pollard-damage-assessment   pollard        44            0      146           0          25
```

`prefix` changes a collection's prefix. It refuses while decisions are filed under the old ids, unless `--rekey` rewrites them.

Once you have made decisions, rename a collection this way rather than renaming its file.

| Option | Does |
|---|---|
| `--rekey` | Rewrites the decisions filed under the old prefix |
| `--no-build` | Skips the rebuild |

## defaults

```sh
hydra-ctl defaults
hydra-ctl defaults off generic
hydra-ctl defaults on
hydra-ctl defaults restore hints params
hydra-ctl defaults restore --all
```

[See the output of each example](output.md#defaults)

Hydra ships some generic defaults. `defaults/positions.yaml`, `positions.yaml` and `hints.yaml` contain the default mappings for a basic hierarchy with symbology and aliases for their ranks.

Only change these if you want to set your own custom hierarchy.

`defaults` shows each default config file (generic, hierarchy, hints, direction, collate, params, artifact) as shipped, changed, missing or off:

```text
generic    default
hierarchy  changed
hints      changed
direction  default
collate    default
params     default
artifact   default
```

`off` and `on` switch generic, hierarchy or hints off or back on, in `hydra.yaml`. `restore` generates the boilerplate again in case it gets mangled, backing up yours first.

| Option | Does |
|---|---|
| `--all` | With restore, restores every default |
| `--yes` | With restore, doesn't wait for Enter |

## hints

```sh
hydra-ctl hints
hydra-ctl hints set portrait ~/pics/pollard.webp --schema Person --name "Jonathan Jay Pollard"
hydra-ctl hints set thumb icons/crown.svg --position Analyst
hydra-ctl hints set thumb ~/pics/flask.svg --titled "fighter pilot|secretary"
hydra-ctl hints set logo ~/pics/tf168.webp --schema PublicBody --name "Task Force 168"
```

[See the output of each example](output.md#hints)

`hints` lists the rules in `hints.yaml`, numbered the way `check` names them (`hints[4]`), with how many nodes each one put an image on in the last build.

### hints set

`hints set` links an image to every entity a match picks, without editing YAML by hand. Give it `portrait`, `thumb` (an icon) or `logo`, the image, and one or more of these:

| Option | Picks |
|---|---|
| `--schema <type>` | Entities of that type and its subtypes |
| `--position <position>` | Entities in that position |
| `--titled <text>` | Entities with a stated title that contains it (a regular expression; case and accents are ignored) |
| `--name <name>` | The entity's name (aliases are not read) |

When you give several, all of them must hold. Anything wider (aliases, other fields, `any:`) goes into `hints.yaml` by hand; see [Images and badges](../guides/hints.md).

The image is copied into `.hydra/resources/` (`portraits/`, `icons/` or `logos/`) unless it is already inside it. A different file with the same name is never overwritten: rename yours, or point at the one already there.

The rule is added to the end of `hints.yaml`, quoted correctly and with your comments left alone. If `check` finds a problem with it (an unknown type or position, or a bad pattern), the file is put back as it was.

After rebuilding, it says how many nodes the rule reached, or that it matches nobody yet.

| Option | Does |
|---|---|
| `--no-build` | Adds the rule without rebuilding |
