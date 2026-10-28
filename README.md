<div align="center">

# open-hydra

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/meridiangray)

[![Version](https://img.shields.io/badge/version-0.1.0-blue)](src/hydra/__init__.py)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](#)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue)](LICENSE)
[![FollowTheMoney](https://img.shields.io/badge/data-FollowTheMoney-6f42c1)](https://followthemoney.tech)
[![MCP server](https://img.shields.io/badge/MCP-hydra--mcp-black)](https://github.com/meridiangray/open-hydra-mcp)

</div>

Hydra translates evidence into data points with a simple framework. It gives investigators simple interfaces for the hard parts of labelled data: sources that conflict, provenance for every value, and hierarchies that render easily to a directed graph.

open-hydra expects [FollowTheMoney](https://github.com/alephdata/followthemoney) style data with one important difference: open-hydra uses field values and not entity IDs as field values. 

## What it looks like

Every example below uses a small demo archive built from the public record of one espionage case: Jonathan Pollard, from a declassified damage assessment.

Records become a tree, drawn once under one parent, with every other parent listed so nothing is hidden:

```text
$ hydra-ctl tree "task force"
Task Force 168 (PublicBody)
└── Jonathan Jay Pollard (Person) — Analyst
      also  Anti-Terrorist Alert Center                   Employment   analyst
      also  Naval Ocean Surveillance Information Center   Employment   research analyst
      also  Navy Field Operational Intelligence Office    Employment   analyst
```

Every value keeps the record, collection and source it came from:

```text
$ hydra-ctl claims pollard
entity                 type     id                       claims   collections
Jonathan Jay Pollard   Person   pollard:per-w3v2f7z7pe        4             1

    field       value                    record                   collection
    alias       Jonathan Pollard         pollard:per-w3v2f7z7pe   pollard-damage-assessment
    name        Jonathan Jay Pollard     pollard:per-w3v2f7z7pe   pollard-damage-assessment
    sources     pollard:doc-v9g25vcmkx   pollard:per-w3v2f7z7pe   pollard-damage-assessment
    weakAlias   Pollard                  pollard:per-w3v2f7z7pe   pollard-damage-assessment
    …
```

When the sources disagree, Hydra asks instead of guessing. Here a second file calls the same man "Jonathan Pollard", and it asks whether they are one entity:

```text
[1/1] Merge
  Jonathan Pollard   and   Jonathan Jay Pollard

  pollard:per-k3m8v1qz5t   Person
     alias       Jay Pollard
     birthDate   1954
     name        Jonathan Pollard
     notes       Navy analyst, arrested in 1985

  pollard:per-w3v2f7z7pe   Person
     alias       Jonathan Pollard
     name        Jonathan Jay Pollard
     sources     pollard:doc-v9g25vcmkx
     weakAlias   Pollard

  [all fields]   fields in both   conflicting fields      Tab / Shift+Tab
Which is better?
  1  one entity
  2  two entities
  ? not sure   u undo   q quit
```

And any tree exports as a Mermaid chart, which renders right here on GitHub (`hydra-ctl tree israeli --format mermaid --vertical`):

```mermaid
flowchart TD
    %% record tree — pollard (GENERATED)
    org-ez802bp11f["Israeli Air Force"]
    per-6q0b4zamfq["Aviem Sella<br/><i>fighter pilot</i>"]
    org-6t8fkjn4kr["Israeli Consulate New York"]
    per-p8w1q8cajn["Joseph Yagur<br/><i>Counselor for Scientific Affairs</i>"]
    org-xfqaxke58a["Israeli Embassy in Washington, D.C."]
    per-jyft1ret42["Ilan Ravid<br/><i>Attache for Scientific Affairs</i>"]
    per-89cafr9tn9["Irit Erb<br/><i>secretary</i>"]
    org-ez802bp11f -->|"fighter pilot"| per-6q0b4zamfq
    org-6t8fkjn4kr -->|"Counselor for Scientific Affairs"| per-p8w1q8cajn
    org-xfqaxke58a -->|"Attache for Scientific Affairs"| per-jyft1ret42
    org-xfqaxke58a -->|"secretary"| per-89cafr9tn9
```

## How it works

An archive is a folder: your records in `collections/`, the rules that shape the hierarchy, and every decision you make in review. `hydra-ctl build` compiles it the same way every time, so two builds of the same archive give the same files, byte for byte.

When you're done, `hydra-ctl pack` turns the archive into one portable `.hydra` file, and `hydra-ctl export` writes it for other tools. Standard FollowTheMoney goes to Aleph and OpenSanctions tooling, and CSV or GraphML goes to Neo4j, Gephi and Cytoscape.

Hydra reads standard FollowTheMoney as it comes. Its own dialect writes links as names instead of ids, which is easier for people (and AI assistants) to write by hand.

## Install

Python 3.11 or later, from GitHub:

```sh
uv tool install git+https://github.com/meridiangray/open-hydra      # or: pip install git+https://github.com/meridiangray/open-hydra
```

## Try it on the demo

```sh
git clone --depth 1 https://github.com/meridiangray/open-hydra
hydra-ctl init demo --name "Pollard case" --prefix pollard
cp open-hydra/examples/demo/collections/*.json demo/collections/
cp open-hydra/examples/demo/.hydra/rules/positions.yaml demo/.hydra/rules/
mkdir -p demo/.hydra/sources/entries
cp open-hydra/examples/demo/.hydra/sources/entries/*.json demo/.hydra/sources/entries/
cd demo
hydra-ctl build
hydra-ctl tree "task force"
```

## Quick start

```sh
hydra-ctl init case --name "My Case"     # a new archive
cp ~/exports/*.json case/collections/    # your FollowTheMoney records
cd case
hydra-ctl build                          # merge, place, find the open questions
hydra-ctl tree                           # the org chart
hydra-ctl review                         # answer the questions one by one
```

## With an AI assistant

[hydra-mcp](https://github.com/meridiangray/open-hydra-mcp) is an MCP server that lets an assistant like Claude read a document, write its facts as records and save them to your archive, with the document kept as the source every entity cites. Anything uncertain is left for you in `hydra-ctl review`.

## Documentation

The full guide covers every command and flag, with the real output of each: [guide/docs](guide/docs/index.md).

## License

Copyright (c) 2026 Meridian Gray. Hydra's program code is free software under the [GNU Affero General Public License, version 3 only](LICENSE). If you run a modified version as a network service, the AGPL requires you to offer its users the source of your changes. The template that `hydra-ctl init` copies into every archive (the schema, rules and settings files) is MIT licensed, so an archive you create is yours to license as you like; your records and sources are not part of Hydra. The vendored FollowTheMoney schema keeps its own MIT license (the FollowTheMoney authors, OCCRP / Alephdata). See [NOTICE.md](NOTICE.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Before a pull request can merge, you agree once to the [Contributor Agreement](CLA.md).
