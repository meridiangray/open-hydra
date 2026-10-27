"""Layer 4a: per-class indices for finding candidate records.

One `ClassIndex` per concrete schema, built from match-category properties
only: an exact index for identifier-like types (identifier, iban, email,
phone, url; each normalized by its type) and a word index for names and
addresses. The word index only narrows candidates; `types.compare_name` decides
exact, subset or neither. Per-class, so an identifier shared by chance across
two kinds of record never becomes a candidate pair.

`search()` is the permissive, ranked browse used to fill pick-lists for a
person (and by `Similar` records); it never drives an automatic decision."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from hydra.identity import types
from hydra.shape.captions import caption


_SUBSET_LIMIT = 10      # words; above this a value's subsets are not enumerated


@dataclass
class ClassIndex:
    schema_name: str
    identifier_index: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    name_token_index: dict[str, list[str]] = field(default_factory=dict)
    records: dict[str, dict] = field(default_factory=dict)
    name_values: dict[str, list[str]] = field(default_factory=dict)  # record_id -> raw TOKEN_TYPES values
    word_sets: dict[frozenset, set[str]] = field(default_factory=dict)  # a value's word set -> record ids
    postings: dict[str, set[str]] = field(default_factory=dict)         # word -> record ids
    rid_words: dict[str, list[frozenset]] = field(default_factory=dict)  # record id -> its values' word sets
    captions: dict[str, str] = field(default_factory=dict)              # record id -> its caption, once

    def add(self, record: dict, prop_classes: dict) -> None:
        rid = record["id"]
        self.records[rid] = record
        self.captions.pop(rid, None)
        self.name_values.setdefault(rid, [])
        for prop, vals in (record.get("properties") or {}).items():
            pc = prop_classes.get(prop)
            if not pc or not pc.match:
                continue
            if pc.ftm_type in types.EXACT_TYPES:
                norm = types.NORMALIZERS[pc.ftm_type]
                for v in vals:
                    n = norm(v)
                    if n:
                        self.identifier_index.setdefault((pc.ftm_type, n), []).append(rid)
            elif pc.ftm_type in types.TOKEN_TYPES:
                self.name_values[rid].extend(vals)
                for v in vals:
                    for tok in types.norm_text(v).split():
                        self.name_token_index.setdefault(tok, []).append(rid)
                    words = types.name_key(v)[1]
                    if words:
                        self.word_sets.setdefault(words, set()).add(rid)
                        self.rid_words.setdefault(rid, []).append(words)
                        for tok in words:
                            self.postings.setdefault(tok, set()).add(rid)

    def match_value(self, value: str, ftm_type: str) -> set[str]:
        """Candidate record ids for a single bare value of a known type —
        used both for reference resolution (merge.py) and as the building
        block of candidate_ids() below. Narrowing only: EXACT_TYPES match
        exactly, TOKEN_TYPES share >=1 token — never itself exact/subset/
        neutral, that decision is always compare_name's."""
        if ftm_type in types.EXACT_TYPES:
            n = types.NORMALIZERS[ftm_type](value)
            return set(self.identifier_index.get((ftm_type, n), [])) if n else set()
        if ftm_type in types.TOKEN_TYPES:
            hits: set[str] = set()
            for tok in types.norm_text(value).split():
                hits.update(self.name_token_index.get(tok, []))
            return hits
        return set()

    def subset_hits(self, value: str) -> set[str]:
        """Record ids with a name or address value whose words equal, contain or
        are contained in `value`'s: exactly the records compare_name() could
        call an exact or subset match, found without scanning everyone who
        shares one common word. A superset of compare_name's matches, never
        less; callers still compare."""
        words = types.name_key(value)[1]
        if not words:
            return set()
        posts = sorted((self.postings.get(t, set()) for t in words), key=len)
        hits = set(posts[0]).intersection(*posts[1:]) if posts[0] else set()   # contain all its words
        if len(words) <= _SUBSET_LIMIT:                                          # contained in it
            toks = sorted(words)
            for k in range(1, len(toks)):
                for combo in combinations(toks, k):
                    hits |= self.word_sets.get(frozenset(combo), set())
        else:
            hits |= {rid for t in words for rid in self.postings.get(t, ())
                     if any(w <= words for w in self.rid_words.get(rid, ()))}
        return hits

    def candidate_ids_safe(self, record: dict, prop_classes) -> set[str]:
        """candidate_ids() for two records of one `token_safe` class: only the
        records match.may_match() could accept (an equal exact value, or a name or
        address word subset), not everyone sharing a word."""
        rid = record["id"]
        hits: set[str] = set()
        for prop, vals in (record.get("properties") or {}).items():
            pc = prop_classes.get(prop)
            if not pc or not pc.match:
                continue
            for v in vals:
                hits |= (self.subset_hits(v) if pc.ftm_type in types.TOKEN_TYPES
                         else self.match_value(v, pc.ftm_type))
        hits.discard(rid)
        return hits

    def candidate_ids(self, record: dict, prop_classes: dict) -> set[str]:
        """Record ids in this index sharing >=1 identifier-exact or >=1
        name-token with `record`'s own match-category property values."""
        rid = record["id"]
        hits: set[str] = set()
        for prop, vals in (record.get("properties") or {}).items():
            pc = prop_classes.get(prop)
            if not pc or not pc.match:
                continue
            for v in vals:
                hits |= self.match_value(v, pc.ftm_type)
        hits.discard(rid)
        return hits


def build_index(records: list[dict], schema_name: str, prop_classes: dict) -> ClassIndex:
    idx = ClassIndex(schema_name=schema_name)
    for r in records:
        if r.get("schema") == schema_name:
            idx.add(r, prop_classes)
    return idx


# ---- search: a ranked, permissive browse over the same indices -------------

_HOW_TIER = {"identifier": 0, "name-exact": 1, "name-subset": 2, "name-overlap": 3}


@dataclass(frozen=True)
class SearchHit:
    record_id: str
    schema: str
    caption: str
    how: str  # "identifier" | "name-exact" | "name-subset" | "name-overlap"
    query_tokens: int
    candidate_tokens: int
    shared_tokens: int


def _rank(hit: SearchHit) -> tuple:
    return (_HOW_TIER.get(hit.how, 9), hit.candidate_tokens, hit.record_id)


def search(query: str, indices: dict[str, ClassIndex], limit: int = 10) -> list[SearchHit]:
    """Rank every record in `indices` by how well it matches `query`: identifier
    hits, then exact names, then word subsets, closest token count first. Every
    hit carries its token counts so a reviewer can see why it ranks where it does.
    A candidate sharing no word with the query is never found (no fuzzy matching)."""
    q_tokens = set(types.norm_text(query).split())
    hits: dict[str, SearchHit] = {}

    for schema_name, idx in indices.items():
        for etype in types.EXACT_TYPES:
            for rid in idx.match_value(query, etype):
                key = (schema_name, rid)
                hits[key] = SearchHit(rid, schema_name, _caption(idx, rid),
                                      "identifier", 1, 1, 1)

    for schema_name, idx in indices.items():
        if not q_tokens:
            continue
        for rid in idx.subset_hits(query):
            if (schema_name, rid) in hits:
                continue  # identifier hit already authoritative for this record
            best: SearchHit | None = None
            for n in idx.name_values.get(rid, []):
                cmp = types.compare_name(query, n)
                if cmp.signal is not types.Signal.MATCH:
                    continue
                c_tokens = set(types.norm_text(n).split())
                how = "name-exact" if cmp.how == "exact" else "name-subset"
                cand = SearchHit(rid, schema_name, _caption(idx, rid), how,
                                  len(q_tokens), len(c_tokens), len(q_tokens & c_tokens))
                if best is None or _rank(cand) < _rank(best):
                    best = cand
            if best:
                hits[(schema_name, rid)] = best

    ranked = sorted(hits.values(), key=_rank)
    return ranked[:limit]


def _caption(idx: ClassIndex, rid: str) -> str:
    """A record's caption, worked out once per index: the same records come up
    in many searches, and a record is never changed while it is indexed."""
    if rid not in idx.captions:
        rec = idx.records.get(rid)
        idx.captions[rid] = caption(rec) if rec else rid
    return idx.captions[rid]
