"""wikidata — read Wikidata items into FtM records, by the archive's map (.hydra/rules/wikidata.yaml).

    api.py        asking Wikidata for items and property descriptions; answers cached on disk
    mapping.py    the map: which property fills which field, which class is which schema
    read.py       items + map -> FtM records, and a report of what was copied, made, left out, not read
    nominate.py   the claims the map does not read yet, grouped, with the field each could fill
    report.py     how the command prints those reports

The command is `hydra-ctl wikidata import | unread | prop` (hydra/cli/wikidata.py)."""
