"""hydra: an identity and hierarchy compiler over FtM records.

An archive directory in, `.hydra/parsed/*` out (build.py). See README.md and cli.md.

    build.py      the orchestrator
    schema.py     the FTM schema loader       resources.py  shared resources, activation
    ingest.py     parse records, prefix ids      layout.py     archive paths
    identity/     who is the same             structure/    who sits under whom
    review/       questions and answers       shape/        the tree and the read
    common.py, dates.py                       shared helpers"""
__version__ = "0.0.1"
