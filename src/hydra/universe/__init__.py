"""universe — canonical ids (Hs) and the universe layer.

    hid.py       the H-ID format: H-<state><flags>-<body>
    table.py     the H-table, universe/canon.jsonl: rows for published and decided Hs
    layer.py     universe/ in an archive: its manifest, members, collections, pins
    members.py   embed, link, refresh and remove members
    identity.py  which records are one entity across members, and which H each is
    pages.py     one page per H: what the wiki shows
    build.py     the universe build: members + table in, universe/.parsed/ out
    review.py    the table's writers: merge, reject, split, publish, caption
    bridge.py    what the archive build reads from the universe (decisions keyed by H)

Builds read the table and never write it; only review and publishing do, and
a state only moves forward. See `hydra-ctl universe --help`.
"""
