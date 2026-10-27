# open-hydra

Hydra translates evidence into data points with a simple, modular framework. It is a minimal framework that provides simple interfaces for investigative tasks such as conflicting data points, source provenance, and visualization-compatible data.

- An archive is a plain folder of records, rules and review decisions; `hydra-ctl pack` zips it into one `.hydra` file
- Tracking which sources conflict on individual data points
- Tree generation of hierarchies (i.e., family, employment, organizational)
- Resolves most data fields into directed graphs

Hydra reads and writes standard FollowTheMoney JSON, as Aleph and OpenSanctions use it, and its own variant that writes links as names instead of ids.

!!! warning
    Hydra is in Alpha mode. Core components are still under development and may change before the stable release.

To try it, [install it](installation.md) and follow the [quickstart](quickstart.md). [How Hydra works](concepts/how-hydra-works.md) explains what a build does, and the [command reference](commands/index.md) covers every command and flag.
