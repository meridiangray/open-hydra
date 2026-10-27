# Images and badges

Hints link icons, portraits, logos and badges to entities by the entities' own data. Records never name their own image, and position files never hold media.

The rules live in `.hydra/rules/hints.yaml`, and the images in `.hydra/resources/`. The quickest way to add one is [`hints set`](../commands/settings.md#hints-set), which copies the image in and writes the rule for you:

```sh
hydra-ctl hints set portrait ~/pics/gus.webp --schema Person --name "Gustavo Fring"
hydra-ctl hints set thumb icons/crown.svg --position Leader
```

## hints.yaml

```yaml
hints:
  - match: {position: Leader}
    set:   {thumb: icons/crown.svg}
  - match: {schema: Person, name: Gustavo Fring}
    set:   {portrait: portraits/gus.webp}
  - match: {schema: Company, name: Los Pollos Hermanos}
    set:   {logo: portraits/los-pollos.webp}
  - match: {titled: {contains: "sicario|hitman"}}
    set:   {thumb: icons/target.svg, badge: muscle}
```

Image paths are inside `.hydra/resources/`. A path that leaves it is refused, and `check` reports it.

## Matching

A rule can match a schema, a position, or any field. `name:` means the name only; write `name|alias:` (or `name|weakAlias:`) to reach aliases too, since an alias can be shared by someone else.

`titled:` matches a title the data itself states. That is the entity's own `position`, the `role` on a relationship where it is the member, employee, director, owner or holder (never the other end), or the name and aliases of a post it holds.

A default such as "Member" for a membership with no role is never a stated title. A `titled:` rule only changes what is shown; it never sets a position.

## Rules add up

Images add up instead of replacing each other. Every matching rule adds its `thumb`, `portrait` or `logo` to the entity's list, in file order, with the rule and the field that matched, so a viewer can cycle through them.

The last `badge` set is the main one, and the others stay listed.

## Quoting

Quote a value that contains a comma, a colon or a `#` when it sits inside `{…}`. Unquoted, YAML splits `{name: Gale (no role, position Cook)}` at the comma, so the rule looks for a name of "Gale (no role" and matches nobody.

`check` flags the stray key that comes out. Write it as `{name: "Gale (no role, position Cook)"}`.

## Checking what matched

```sh
hydra-ctl hints
```

```text
   0  {position: Leader}   {thumb: icons/crown.svg}   images on 5
   1  {position: Enforcer}   {thumb: icons/target.svg}   images on 4
   2  {position: Cook}   {thumb: icons/flask.svg}   images on 3
   …
```

Rules are numbered the way `check` names them (`hints[4]`), with how many nodes each one put an image on in the last build.
