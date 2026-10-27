# Quickstart

This walks through one archive from start to finish. You need [`hydra-ctl` installed](installation.md) and some FollowTheMoney JSON records.

## 1. Create an archive

```sh
hydra-ctl init case --name "My Case" --prefix mc
cd case
```

`init` creates the folder from the built-in template. [Hydra Archives](concepts/archive.md) explains what is in it.

## 2. Add records

Copy your `.json` files into `collections/`, or load one with `import`, which checks that it reads as records first:

```sh
hydra-ctl import ~/exports/people.json --format ftm
```

## 3. Build

```sh
hydra-ctl build      # merge, place and write .hydra/parsed/
hydra-ctl check      # problems in the files
```

## 4. Look around

```sh
hydra-ctl details                  # one-screen summary
hydra-ctl tree                     # the org chart
hydra-ctl claims "Some Name"       # where each value came from
hydra-ctl sources                  # which documents cite what
```

## 5. Answer the open questions

```sh
hydra-ctl todo       # count what is open
hydra-ctl review     # answer them one by one
```

[Reviewing](guides/reviewing.md) shows what each question looks like.

## 6. Share it

```sh
hydra-ctl pack                         # one portable .hydra file
hydra-ctl export --format graphml      # for Gephi, yEd, Cytoscape
```
