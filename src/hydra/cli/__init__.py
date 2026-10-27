"""The hydra command line: `hydra-ctl <command> ...` (from a working tree: `python3 -m hydra <command>`).

Each command is its own module with a `main(argv)`; this only dispatches.
Commands that read `.hydra/parsed/` never build; `build` writes `.hydra/parsed/`."""
from __future__ import annotations

import sys

# The command list, grouped in the order a person meets the commands. Each entry:
# name -> (module[:function], one-line help). `shown` overrides the name printed.
GROUPS = {
    "Start": {
        "init": ("hydra.cli.init", "Create an archive, or open a .hydra file into one"),
        "activate": ("hydra.cli.activate", "Use this archive when <dir> is left out"),
        "deactivate": ("hydra.cli.activate:deactivate", "Stop using the active archive"),
    },
    "Build": {
        "import": ("hydra.cli.importer", "Load FtM JSON (standard or hydra's), CSV or GraphML as a collection"),
        "build": ("hydra.cli.build", "Compile collections/ into .hydra/parsed/"),
        "check": ("hydra.cli.check", "Find problems in the archive's files, without building"),
    },
    "Explore": {
        "details": ("hydra.cli.details", "Summary: records, types, tree, open questions"),
        "tree": ("hydra.tree", "Show the record tree, from a type or a search"),
        "positions": ("hydra.cli.positions", "Show the position tree and the titles no position takes"),
        "claims": ("hydra.claims", "Show where each value of an entity came from"),
        "sources": ("hydra.sources", "List the sources, and which entities cite each"),
        "node": ("hydra.cli.node", "Find the nodes closest to a value"),
    },
    "Decide": {
        "todo": ("hydra.cli.todo", "List what the last build needs a person to decide"),
        "review": ("hydra.cli.review", "Answer the open questions one by one"),
        "answer": ("hydra.cli.answer", "Record one decision, then rebuild"),
        "reset": ("hydra.cli.reset", "Remove decisions (backs them up first)"),
        "stubs": ("hydra.cli.stubs", "List names that link to no record; graduate one into an entity"),
    },
    "Share": {
        "pack": ("hydra.cli.pack", "Pack an archive into one portable .hydra file"),
        "unpack": ("hydra.cli.pack:unpack_main", "Unpack a .hydra file into a folder"),
        "export": ("hydra.cli.export", "Export the archive as FtM JSON lines (standard or hydra's), CSV or GraphML"),
    },
    "Settings": {
        "collections": ("hydra.cli.collections", "List collections and their id prefixes; change one"),
        "defaults": ("hydra.cli.defaults", "Check, switch off, or restore the default config files"),
        "hints": ("hydra.cli.hints", "List the image and badge rules; link an image file by one"),
    },
}
COMMANDS = {name: entry for group in GROUPS.values() for name, entry in group.items()}
SHOWN = {"node": "node find"}
ALIASES = {"position": "positions"}
READ_ONLY = {"check", "details", "tree", "positions", "todo", "node", "claims", "sources", "export"}   # commands that write no archive file


def usage() -> str:
    width = max(len(SHOWN.get(n, n)) for n in COMMANDS) + 2
    lines = ["Hydra: compile FtM records into a reviewed archive.", "",
             "usage: hydra-ctl <command> [<dir>] [options]"]
    for title, group in GROUPS.items():
        lines += ["", f"{title}:"]
        lines += [f"  {SHOWN.get(n, n):<{width}}{help_}" for n, (_, help_) in group.items()]
    lines += ["", "Run 'hydra-ctl <command> --help' for a command's options."]
    return "\n".join(lines)


def run() -> int:
    """The installed entry point: main(), with `hydra: …` errors styled."""
    try:
        return main()
    except SystemExit as e:
        if isinstance(e.code, str) and e.code.startswith("hydra: "):
            from hydra.cli import style
            style.error(e.code[len("hydra: "):])
            return 1
        raise
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    if args[0].rstrip("/") in COMMANDS:
        args[0] = args[0].rstrip("/")           # shell completion inside an archive adds the folder's slash
    args[0] = ALIASES.get(args[0], args[0])
    if args[0] not in COMMANDS:
        from hydra.cli import style
        style.error(f"unknown command '{args[0]}'. Run 'hydra-ctl' for the command list.")
        return 2
    import importlib
    mod, _, fn = COMMANDS[args[0]][0].partition(":")
    run_it = getattr(importlib.import_module(mod), fn or "main")
    try:
        if args[0] in READ_ONLY or (args[0] == "collections" and args[1:2] != ["prefix"]) \
                or (args[0] == "stubs" and args[1:2] not in (["graduate"], ["drop"])) \
                or (args[0] == "hints" and args[1:2] != ["set"]):
            from hydra import yamlcache
            with yamlcache.frozen():              # changes nothing: each file is looked at once
                return run_it(args[1:])
        return run_it(args[1:])
    except Exception as e:                        # any command that builds an archive with no records
        from hydra.build import NothingToBuild
        if isinstance(e, NothingToBuild):
            raise SystemExit(f"hydra: {e}") from None
        raise
