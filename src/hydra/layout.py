"""
Single Source of Truth for Hydra V1 archive paths and layout formatting.
"""

FORMAT_VERSION = 2

# Archive Root: what a person works in. Everything the build and review manage
# sits in one hidden folder, INTERNAL.
MANIFEST = "hydra.yaml"
INTERNAL = ".hydra"
SOURCES_DIR = f"{INTERNAL}/sources"
SOURCE_ENTRIES = f"{SOURCES_DIR}/entries"       # the sources records cite (Article, Document...): `sources` points here
SOURCE_COLLECTION = "sources/"                   # a source file's collection name: sources/<file name>
RESOURCES_DIR = f"{INTERNAL}/resources"       # icons and media that hints.yaml points at

# Authored Rules
RULES_DIR = f"{INTERNAL}/rules"
POSITIONS = f"{RULES_DIR}/positions.yaml"      # this archive's own positions
DEFAULT_POSITIONS = f"{RULES_DIR}/defaults/positions.yaml"   # the positions hydra ships
HINTS = f"{RULES_DIR}/hints.yaml"
VOCABULARIES = f"{RULES_DIR}/vocabularies.yaml"   # the words a status or capacity takes, and what each means
CAPACITY = f"{RULES_DIR}/capacity.yaml"           # when an agent's office makes the client's interest theirs
KEYS = f"{RULES_DIR}/keys.yaml"                   # the namespaces of keys other systems give entities, and the primary one
STANDARDS = f"{RULES_DIR}/standards.yaml"         # what ISO code lists do not say: labels, demonyms, coded properties
GROUPS = f"{RULES_DIR}/groups.yaml"               # organizations whose members a page names as a group (a house, a party)
KINSHIP = f"{RULES_DIR}/kinship.yaml"             # what each Family word says: parent, child, sibling, spouse, gender
WIKIDATA = f"{RULES_DIR}/wikidata.yaml"           # which Wikidata properties fill which fields when an item is imported
SCOPE = f"{RULES_DIR}/scope.yaml"                # what the archive is about; the rest is context, not listed
REVIEW_DIR = f"{INTERNAL}/review"         # written by review commands, not by hand
VERDICTS = f"{REVIEW_DIR}/verdicts.yaml"
PARAMS_DIR = f"{INTERNAL}/schema/params"                   # <Type>.param.yaml match/distinct/fold policy

# Schema (Types, Ontologies)
SCHEMA_DIR = f"{INTERNAL}/schema"
EXTENSIONS_DIR = f"{SCHEMA_DIR}/extensions"      # types hydra adds on top of FtM
ARTIFACT = f"{EXTENSIONS_DIR}/artifact.yaml"
COLLATE = f"{EXTENSIONS_DIR}/collate.yaml"
DIRECTION = f"{SCHEMA_DIR}/direction.yaml"      # which end of each relationship is the parent; which are sideways
FTM_DIR = f"{SCHEMA_DIR}/ftm"


# Collections (Data plane)
COLLECTIONS_DIR = "collections"
COLLECTIONS_MANIFEST = f"{COLLECTIONS_DIR}/manifest.json"

# Parsed Outputs (Derived JIT Tables)
PARSED_DIR = f"{INTERNAL}/parsed"
PARSED_YAML = f"{PARSED_DIR}/parsed.yaml"
BUILD_YAML = f"{PARSED_DIR}/build.yaml"
READS = {"declared": f"{PARSED_DIR}/declared.json",    # the two reads a build writes, by the name `--read` takes
         "generic": f"{PARSED_DIR}/generic.json"}
CLAIMS_JSONL = f"{PARSED_DIR}/claims.jsonl"
IDENTICAL_JSONL = f"{PARSED_DIR}/identical.jsonl"
LEDGER_JSONL = f"{PARSED_DIR}/ledger.jsonl"
CACHE_DIR = f"{INTERNAL}/cache"

# History: snapshots of the authored files (never of what a build recomputes)
HISTORY_DIR = f"{INTERNAL}/history"

# Universe layer: a parallel layer beside the archive's own (see hydra/universe/)
UNIVERSE_DIR = "universe"
UNIVERSE_MANIFEST = f"{UNIVERSE_DIR}/universe.yaml"
CANON = f"{UNIVERSE_DIR}/canon.jsonl"                    # the H-table: written by review and publishing only
UNIVERSE_VERDICTS = f"{UNIVERSE_DIR}/review/verdicts.yaml"
UNIVERSE_WIKI = f"{UNIVERSE_DIR}/wiki.yaml"              # the universe's own wiki config: over every member's
UNIVERSE_COLLECTIONS = f"{UNIVERSE_DIR}/collections"
UNIVERSE_MEMBERS = f"{UNIVERSE_DIR}/members"
UNIVERSE_PARSED = f"{UNIVERSE_DIR}/.parsed"              # what `universe build` writes, and all it writes
