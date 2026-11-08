# hydra-mcp

`hydra-mcp` ([source on GitHub](https://github.com/meridiangray/open-hydra-mcp)) is an [MCP](https://modelcontextprotocol.io) server that lets an AI assistant turn a file into records for a Hydra archive. The assistant reads the file, writes the facts as Hydra's FollowTheMoney JSON, and the server checks them and saves them with the file as the evidence every entity cites.

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

<!-- tools:start -->
| Tool | Arguments | What it does |
|---|---|---|
| `labelling_guidelines` | `archive` | How to model records so hydra reads them correctly: the record format, one record per entity, which field each end of a relationship goes in, roles in the source's words, Family's direction, organizations inside organizations, offices, dates, and this archive's relationship fields and position ladder. |
| `read_file` | `path`, `offset`, `archive` | The text of a file (.txt, .md, .html, .pdf, .docx), read exactly as it will be stored as evidence. |
| `find_entities` | `query`, `schema`, `archive`, `limit` | Entities already in the archive closest to a name, best first, each with what tells it apart from its namesakes (`facts`: dates, nationality, posts; `links`: parents and relationships), its canonical id `h` and the `keys` it holds. |
| `explain_entity` | `entity`, `archive` | Where every value of one entity came from (`entity`: its id, or a name): each property's values with the records, collections and documents behind them, its canonical id, and the review questions it takes part in. |
| `open_questions` | `kind`, `offset`, `limit`, `archive` | What the last build asks a person to decide: `merges` (are these one entity?), `references` (which record does this name mean?), `placements`, `stale` decisions, `contradictions`, and problems with `verdicts`. |
| `answer` | `id`, `choice`, `confirm`, `archive` | Answer one open question (`id` from `open_questions`): `confirm` or `reject` a merge or placement, a candidate's number, a record id or `none` for a reference, a name for a caption (`cap-<id>`), or `clear` to take an answer back. |
| `amend_records` | `collection`, `records`, `remove`, `archive` | Correct a saved collection: each record with an `id` already in it replaces that record whole (give every property it should keep; its evidence stays cited); a record with a new or no id is added; `remove` drops records by id. |
| `preview` | `records`, `archive` | What saving a batch would change, built aside, writing nothing: the entities it adds, the merges it would make, the questions it would raise, and links that would stay names. |
| `pin_upstream` | `collection`, `record`, `h`, `confirm`, `archive` | Pin a saved record to an entity's canonical id `h` (from `find_entities`): the record is that entity from now on. |
| `set_positions` | `positions`, `confirm`, `archive` | Write this archive's rank ladder (.hydra/rules/positions.yaml): {name: {below: [the positions above it], titles: [the role words that mean it], outside: false}}. The preview says how many of the archive's roles each position ranks and which roles none takes. |
| `link_images` | `images`, `confirm`, `archive` | `link_image` for many images at once: [{image, kind, name, schema, ...}, ...]. Previews unless confirm=true. |
| `wiki_readiness` | `archive` | What keeps the archive's wiki pages from being complete, each as something to record or decide: terms with no years, names that link to no record, links that name several records, same-name pairs, facts only in notes, people with no dates, unsourced pages, facts that contradict each other. |
| `history_log` | `limit`, `archive` | The archive's snapshots, newest first: who changed what (every save, answer and amend made here is one, by agent:hydra-mcp). |
| `history_diff` | `a`, `b`, `archive` | What changed between two snapshots (`b` left out: the files as they are now): each file, and inside a collection the records added, removed and changed. |
| `history_restore` | `ref`, `paths`, `confirm`, `archive` | Put the archive's files (or just `paths`) back as they were at snapshot `ref` (an id, or HEAD~1 for one change back). |
| `describe_schema` | `schema`, `archive` | The entity types and relationships records can use. |
| `universe_build` | `archive` | Build the universe from the last archive build: which records are one entity, each entity's canonical id (H) and the wiki pages. |
| `publish` | `hs`, `collections`, `confirm`, `archive` | Make computed Hs published, so their ids and page addresses hold from now on: `hs` (Hs, bodies or record ids), or every computed H whose records all come from `collections` (entities that also draw on other collections are listed, not published). |
| `scope` | `entity`, `archive` | What the archive is about (.hydra/rules/scope.yaml): how many entries are in scope, the context ones (kept in the data, named as text on the pages that mention them, listed nowhere), and for `entity` (an H, key, record id or title) whether it is in scope and why ("Ownership from <a seed entity>"). |
| `set_scope` | `include`, `exclude`, `seeds`, `confirm`, `archive` | Change what the archive is about: add entries to `include` or `exclude` (Hs, keys, record ids, titles, or `collection:<name>`), or set the seed collections. |
| `stubs` | `archive` | Names that links hold but no record has (the wiki's red links): how many links name each, from which fields, and what kind of entity they fit; and those already graduated. |
| `graduate_stub` | `name`, `as_schema`, `confirm`, `archive` | Make a stub (see `stubs`) a bare entity every link naming it points at, as `as_schema` (default: what its links fit). |
| `wiki_serve` | `port`, `theme`, `replace_other`, `archive` | Show the archive as a wiki at http://127.0.0.1:<port>/, current: builds the pages when they are older than their inputs, stops the wiki this tool started on that port, starts a new one and checks it serves as many entries as the build made pages (`ok`). |
| `wiki_stop` | `port` | Stop the wiki this tool started on `port`. |
| `keys` | `archive` | The key namespaces of this archive (.hydra/rules/keys.yaml): for each, its label, link, the FtM property holding the same key, whether an entity may hold only one (`unique`); `primary`, the namespaces an entity is keyed by first (its H comes from that key); and how many entities hold a key of each namespace, undeclared ones listed. |
| `vocabularies` | `archive` | The words a status or capacity field takes in this archive, and what hydra does with each: {name: {applies_to: ["Interest.status", ...], values: {word: {label, why, ended, caveat, beneficiary}}}}. `ended` means the record counts as over, `caveat` that it is flagged wherever the fact is shown. |
| `check_records` | `records`, `collection`, `source`, `archive` | Dry run of `save`: checks proposed records and writes nothing. |
| `fetch_source` | `url`, `title`, `published`, `author`, `archive` | Fetch a web page and keep its text in the archive as a source of its own (an Article), so records can cite it: `"sources": ["<source_id>"]`, with their `notes` quoting it word for word. |
| `read_source` | `source`, `offset`, `find`, `archive` | A kept source's text (by its id, from `fetch_source` or `save`), in parts from `offset`; or, with `find` (words), every sentence containing one of them: the sentences to quote in `notes`. |
| `source_report` | `top`, `archive` | Where the archive's facts come from: citations counted by origin (the site a URL belongs to), the W-factor (of the citations that cite anything, the share resting on Wikipedia alone) for the archive and each collection, how many cite nothing, and the entries that rest most on Wikipedia, each with the records to re-source (record, collection, Wikipedia URL, the quote). |
| `wikipedia_footnotes` | `url`, `quote` | What Wikipedia itself cites for a sentence: given the article `url` a record cites and the `quote` it took from it, the references attached to that sentence (url, title, publisher, date). |
| `swap_source` | `collection`, `record`, `source`, `quote`, `confirm`, `archive` | Re-source a saved record: its Wikipedia citation out, the kept source `source` (from `fetch_source`) in, with `quote` (word for word in that source, checked) as its note. |
| `read_page` | `entity`, `archive` | An entry's wiki page as a reader sees it (by H, key, record id or title): whether it is in scope, the infobox rows, the lead, every section's text in order, and the footnotes [n] resolved to the record, collection, source and quote behind each. |
| `get_records` | `collection`, `name`, `offset`, `limit`, `archive` | Read back what the archive holds. |
| `save` | `records`, `source`, `collection`, `archive`, `replace` | Check and save records as a new collection, with their evidence, then rebuild. |
| `link_image` | `image`, `kind`, `schema`, `position`, `titled`, `name`, `confirm`, `archive` | Give entities an image or icon through a rule in hints.yaml (records never carry images). |
| `create_archive` | `path`, `name`, `prefix`, `confirm` | Start a new, empty hydra archive in a new or empty folder (full path, chosen by the person). |
<!-- tools:end -->

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

To undo a save, look at it with `history_log` and `history_diff`, then put the files back with `history_restore` (previewed first; the restore is itself a snapshot). Then run `universe_build`.

## Choosing the archive

The archive is, in order: the tool's `archive` argument, the `HYDRA_ARCHIVE` environment variable, an archive activated with `hydra-ctl activate` in or above the folder the server starts in, or that folder if it is an archive.

With no archive, nothing is written. `labelling_guidelines`, `read_file`, `describe_schema` and `check_records` still work on Hydra's defaults, `find_entities` returns nothing, and `save`, `get_records` and `link_image` refuse and tell the assistant to ask you for a folder or offer `create_archive`.

A path that is named but isn't an archive is an error, never a quiet fallback.

## Setup

### 1. Install

`hydra-mcp` is a Python package with a `hydra-mcp` command, like `hydra-ctl`. It depends on `open-hydra`, the main [open-hydra](https://github.com/meridiangray/open-hydra) package. Neither is on PyPI, so install both from GitHub in one go:

```sh
uv tool install git+https://github.com/meridiangray/open-hydra-mcp --with git+https://github.com/meridiangray/open-hydra
```

Or with pip, into any environment:

```sh
pip install git+https://github.com/meridiangray/open-hydra git+https://github.com/meridiangray/open-hydra-mcp
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

**Windows:** give the full path and double every backslash:

```json
"command": "C:\\Users\\you\\.local\\bin\\hydra-mcp.exe",
"env": {"HYDRA_ARCHIVE": "C:\\cases\\case"}
```

**Installed in WSL, client on Windows:**

```json
"command": "wsl",
"args": ["-d", "Debian", "--", "bash", "-lc", "HYDRA_ARCHIVE=/mnt/c/cases/case hydra-mcp"]
```

### Updating

To update, run the install again with `uv tool install --reinstall` (or `pip install --force-reinstall`) and restart the client.
