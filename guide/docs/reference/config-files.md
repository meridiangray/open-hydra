# Config files

## hydra.yaml

The archive's own settings.

| Key | Is |
|---|---|
| `name` | The archive's name, asked by `init` |
| `prefix` | The id prefix every collection uses unless it has its own, asked by `init` |
| `ftm` | The hash of the FollowTheMoney schema the archive was made with; every export is stamped with it |
| `defaults_off` | The default rule files you switched off with `hydra-ctl defaults off` |
| `subject` | Optional. Names the organization the archive charts |
| `search` | Optional. Sets how far searches look when no flag says: `all` (the default), `no-text` (every field but free text) or `names` (names and ids) |
| `format` | The archive layout's version, written by `init` |

## .hydra/rules/

`positions.yaml` is your archive's own hierarchy, and `defaults/positions.yaml` holds the generic positions it builds on. Both are covered in [Defining Hierarchies](../guides/hierarchy.md).

`hints.yaml` links icons, portraits, logos and badges to entities; see [Images and badges](../guides/hints.md).

## .hydra/review/verdicts.yaml

Written by `hydra-ctl review` and `hydra-ctl answer`: one line per decision (this merge confirmed, that placement rejected). It is read on every build and travels with the archive.

`hydra-ctl reset` removes decisions, after backing the file up.

## .hydra/schema/

The FollowTheMoney schema the archive uses, and Hydra's settings for it. These are background configuration: you can change them, but probably shouldn't. `hydra-ctl defaults` shows whether they are as shipped and restores them.

| Path | Is |
|---|---|
| `ftm/followthemoney/` | The FtM schema itself (types, properties, relationships) |
| `ftm/config/` | FtM's own config files |
| `params/` | One file per type (`Person.param.yaml`…) |
| `direction.yaml` | Which end of each relationship is the parent |
| `extensions/collate.yaml` | A helper for hierarchies and reviews |
| `extensions/artifact.yaml` | Hydra's extension types |

### params

Each param file says which fields decide that two records are the same entity (`match`), which fields keep them apart when they disagree (`distinct`), and which fields place a record under another (`fold`). A list in a param file replaces Hydra's defaults for that category.

### direction.yaml

Says which end of each kind of relationship is the higher one: an Ownership's owner is above what it owns, a Membership's organization above its member. Some relationships are marked sideways (family, associates, lawyers), and those never make a hierarchy.

It is a helper for some annoying logic: leave it alone. It is also where `edge_positions` lives, the opt-in that fills a title in for a role-less Membership, Employment or Directorship.

### artifact.yaml

`extensions/artifact.yaml` (with `collate.yaml`) holds extension types: Hydra's additions to FtM, such as the `sources` field on every entity and notes on relationships.

It is linked to another tool, Scribble, which provides a UI for automated investigative data tasks and exports collection files into a Hydra archive.
