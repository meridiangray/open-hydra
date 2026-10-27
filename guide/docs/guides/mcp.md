# hydra-mcp

`hydra-mcp` is an [MCP](https://modelcontextprotocol.io) server that lets an AI assistant turn a file into records for a Hydra archive. The assistant reads the file, writes the facts as Hydra's FollowTheMoney JSON, and the server checks them and saves them with the file as the evidence every entity cites.

It doesn't guess. Anything uncertain is left for a person: a name that might be someone already in the archive becomes a merge question in `hydra-ctl review`, and a role the hierarchy doesn't rank is reported, not rewritten.

## How a session goes

1. `labelling_guidelines` tells the assistant how to model records for this archive.
2. `read_file` returns the file's text, exactly as it will be stored.
3. `describe_schema` shows the properties and types of each kind of record, and `find_entities` looks each name up, so records reuse the exact name of anyone already in the archive.
4. `check_records` is a dry run: it reports errors, warnings and how each link and role resolves, and writes nothing.
5. `save` checks the records again, writes them and rebuilds. If anything breaks the modelling rules, nothing is written and `errors` says what to fix.
6. `get_records` reads the saved collection back, with each property's type and what every link resolved to, so the assistant can check its work against the file.

You then answer whatever it left open with `hydra-ctl todo` and `hydra-ctl review`.

## Tools

| Tool | Arguments | What it does |
|---|---|---|
| `labelling_guidelines` | `archive` | The record format, which field each end of a relationship goes in, roles, dates, and this archive's relationship fields and position ladder |
| `read_file` | `path`, `offset`, `archive` | The text of a `.txt`, `.md`, `.html`, `.pdf` or `.docx` file. Long files come in parts: call again with `offset` set to `next_offset`. Says whether the archive already holds the file |
| `describe_schema` | `schema`, `archive` | With no `schema`, the record types and relationships. With one, every property it accepts: its type, whether it is required, and what a link takes |
| `find_entities` | `query`, `schema`, `limit`, `archive` | Entities already in the archive closest to a name, best first |
| `check_records` | `records`, `collection`, `archive` | A dry run of `save`: errors, warnings, how links and roles resolve, likely duplicates. Writes nothing |
| `save` | `records`, `source`, `collection`, `replace`, `archive` | Checks and saves records as a new collection with their evidence, then rebuilds |
| `get_records` | `collection`, `name`, `offset`, `limit`, `archive` | Reads a saved collection back with each property's type, what each link resolved to after the build, and the save checks repeated. With no `collection`, lists them |
| `link_image` | `image`, `kind`, `schema`, `position`, `titled`, `name`, `confirm`, `archive` | Previews, then on `confirm=true` adds, a [hints](hints.md) rule giving matching entities a `portrait`, an icon (`thumb`) or a `logo` |
| `create_archive` | `path`, `name`, `confirm` | Previews, then on `confirm=true` creates, an empty archive in a new or empty folder (as `hydra-ctl init`) |

`path` arguments must be full paths. A scanned PDF with no text layer is an error, never an empty source.

### Records

Records use Hydra's dialect: links are written as the linked entity's name, not an id. See [Links](../concepts/records.md#links).

```json
[
  {
    "schema": "Person",
    "properties": {
      "name": [
        "Rob Kerr"
      ],
      "weakAlias": [
        "Kerr"
      ]
    }
  },
  {
    "schema": "PublicBody",
    "properties": {
      "name": [
        "Port Authority"
      ]
    }
  },
  {
    "schema": "Employment",
    "properties": {
      "employee": [
        "Rob Kerr"
      ],
      "employer": [
        "Port Authority"
      ],
      "role": [
        "deputy"
      ],
      "startDate": [
        "2019"
      ]
    }
  }
]
```

`id` is optional. Dates are `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.

### The `source` argument of `save`

`{"file": "/full/path/report.pdf"}` keeps the file as the evidence, `{"text": "..."}` keeps pasted text, and `{"id": "..."}` adds more records from evidence already saved. A file already saved in the archive is refused; save with its `id` instead.

Add `title`, `url` (which makes the source an Article), `publisher`, `author`, `published` or `language` when known.

### Images

Records never carry images. `link_image` adds a rule to `.hydra/rules/hints.yaml` instead, the same rule `hydra-ctl hints set` writes. It only previews until it is called with `confirm=true`, which the assistant should do only after you agree. See [Images and badges](hints.md).

## What a save writes

```
collections/<collection>.json                  the records
.hydra/sources/entries/<collection>.json       the source, as one Document
.hydra/sources/files/<collection>/<file>       a copy of the original file
```

Every entity cites the source in `sources`, so `hydra-ctl claims` and `hydra-ctl sources` trace each value back to the file. Relationships have no `sources` field in FtM; they trace back through their collection.

The collection is named from the file or title plus a timestamp unless you pass `collection`, and an existing one is never overwritten unless `replace=true`. If the rebuild fails, the files are put back as they were.

To undo a save, delete the files it lists in `undo`, then run `hydra-ctl build`.

## Choosing the archive

The archive is, in order: the tool's `archive` argument, the `HYDRA_ARCHIVE` environment variable, an archive activated with `hydra-ctl activate` in or above the folder the server starts in, or that folder if it is an archive.

With no archive, nothing is written. `labelling_guidelines`, `read_file`, `describe_schema` and `check_records` still work on Hydra's defaults, `find_entities` returns nothing, and `save`, `get_records` and `link_image` refuse and tells the assistant to ask you for a folder or offer `create_archive`.

A path that is named but isn't an archive is an error, never a quiet fallback.

## Setup

### 1. Install

`hydra-mcp` is a Python package with a `hydra-mcp` command, like `hydra-ctl`. It depends on `open-hydra` (the `openhydra` repository). Neither is on PyPI, so install both from GitHub in one go:

```sh
uv tool install git+https://github.com/meridiangray/openhydra-mcp --with git+https://github.com/meridiangray/openhydra
```

Or with pip, into any environment:

```sh
pip install git+https://github.com/meridiangray/openhydra git+https://github.com/meridiangray/openhydra-mcp
```

Afterwards `hydra-mcp` is on your PATH. It speaks MCP over stdio, so running it by hand just waits for a client.

### 2. Add it to your client

Every MCP client needs the same two things: the command `hydra-mcp`, and optionally `HYDRA_ARCHIVE` set to the archive's folder. Leave `HYDRA_ARCHIVE` out to choose the archive per conversation.

**Claude Code:**

```sh
claude mcp add hydra --env HYDRA_ARCHIVE=/path/to/case -- hydra-mcp
```

Add `--scope user` to make it available in every project, or `--scope project` to write it to `.mcp.json` for everyone working in the repo.

**Claude Desktop, Cursor, VS Code and other clients** take the standard `mcpServers` JSON. For Claude Desktop it goes in `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "hydra": {
      "command": "hydra-mcp",
      "env": {"HYDRA_ARCHIVE": "/path/to/case"}
    }
  }
}
```

Restart the client, and the tools appear under `hydra`.

If the client can't find the command, give its full path instead. `which hydra-mcp` (macOS, Linux) or `where hydra-mcp` (Windows) prints it.

### Windows with Hydra in WSL

When the client runs on Windows and Hydra is installed inside WSL, start the server through `wsl.exe`. `wsl.exe` doesn't pass Windows environment variables on, so set the archive with `env`:

```json
{
  "mcpServers": {
    "hydra": {
      "command": "wsl.exe",
      "args": ["-d", "Debian", "--", "env", "HYDRA_ARCHIVE=/mnt/c/path/to/case",
               "/home/<user>/.local/bin/hydra-mcp"]
    }
  }
}
```

Windows paths the assistant passes (`C:\cases\port`) are read as their WSL paths (`/mnt/c/cases/port`).

### Updating

To update, run the install again with `uv tool install --reinstall` (or `pip install --force-reinstall`) and restart the client.
