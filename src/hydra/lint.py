"""lint.py — every problem in an archive, as one list of issues.

An issue is `{level, code, file, where, message}`:

    error    the entry was skipped (the build goes on without it)
    warning  probably a mistake
    info     worth knowing; nothing was skipped

`check(root)` finds what the files and the schema alone show (no build needed);
`build_issues(...)` adds what only a build can see (orphan verdicts, dead pins,
hint rules that match nothing, literal and duplicate ids). Only a file that is
not valid YAML or JSON stops a build; everything else lands here."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hydra import dates, layout, resources, schema, yamlcache
from hydra.identity import classify
from hydra.identity.types import norm_text
from hydra.ingest import resolve_prefixes
from hydra.review import verdicts as vd
from hydra.shape import rules
from hydra.structure import fold as fold_mod

LEVELS = ("error", "warning", "info")


def issue(level: str, code: str, file: str, where: str, message: str) -> dict:
    return {"level": level, "code": code, "file": file, "where": where, "message": message}


# ---- shapes ------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Names = list[str] | str | None


class PositionModel(_Strict):
    below: Names = None
    above: Names = None
    titles: Names = None
    outside: bool | None = None


class SetModel(_Strict):
    position: str | None = None
    badge: str | None = None
    thumb: str | None = None
    portrait: str | None = None
    logo: str | None = None


class HintRule(_Strict):
    match: dict[str, Any] | None = None
    set: SetModel | None = None


class HintsFile(_Strict):
    hints: list[HintRule] = []


class DirectionFile(_Strict):
    above: list[str] = []
    lateral: list[str] = []
    dual: list[str] = []
    governing: list[str] = []
    edge_positions: dict[str, str] = {}
    exclude: list[str] = []
    ignore: list[str] = []         # `Schema.prop`: entity properties that are deliberately neither


class ParamFile(_Strict):
    schema_name: str | None = Field(default=None, alias="schema")
    match: list[str] | None = None
    distinct: list[str] | None = None
    fold: list[str] | None = None


DISPLAY_FIELDS = ("thumb", "portrait", "logo", "badge", "icon")   # render fields, filled by hints.yaml only

_NOT_POSITIONS = ("positions", "carry", "hints", "model", "subject")


def _shape(model, doc, file: str, code: str, prefix: str = "") -> list[dict]:
    try:
        model.model_validate(doc)
        return []
    except ValidationError as e:
        return [issue("error", code, file, prefix + ".".join(str(x) for x in err["loc"]),
                      err["msg"] + "; ignored") for err in e.errors()]


def _yaml(root: Path, rel: str, out: list) -> Any:
    p = root / rel
    if not yamlcache.is_file(p) or resources.is_off(root, rel):      # switched off: not read
        return None
    try:
        return yamlcache.load(p)
    except yaml.YAMLError as e:
        out.append(issue("error", "file.yaml", rel, "", f"not valid YAML: {e}"))
        return None


# ---- static checks -----------------------------------------------------------


def check(root, direction: dict | None = None) -> list[dict]:
    """Everything the files and the loaded schema show. `schema.load(root)` first."""
    root = Path(root)
    out: list[dict] = []
    fam_doc = _yaml(root, layout.DIRECTION, out)
    direction = direction if direction is not None else fold_mod.load_direction(
        root / layout.DIRECTION if (root / layout.DIRECTION).is_file() else None)
    generic = _yaml(root, layout.DEFAULT_POSITIONS, out)
    declared = _yaml(root, layout.POSITIONS, out)
    out += _positions(generic, declared)
    out += _hints(root, _yaml(root, layout.HINTS, out), generic, declared, direction)
    out += _direction(fam_doc, direction)
    out += _params(root)
    out += _verdict_values(root)
    out += _collections(root)
    out += _old_layout(root)
    out += _archive_manifest(_yaml(root, layout.MANIFEST, out))
    return out


MANIFEST_KEYS = ("name", "format", "ftm", "prefix", "subject", "search", resources.OFF_KEY)


def _archive_manifest(doc) -> list[dict]:
    """hydra.yaml: its keys and the values a command reads. A value that is not
    understood would be ignored without a word, so it is reported."""
    from hydra.ingest import valid_prefix
    from hydra.query import SEARCH
    rel = layout.MANIFEST
    if doc is None:
        return []
    if not isinstance(doc, dict):
        return [issue("error", "archive.shape", rel, "", "must be a mapping of settings")]
    out = [issue("warning", "archive.unknown-key", rel, str(k), f"'{k}' is not a setting; ignored "
                 f"(settings: {', '.join(MANIFEST_KEYS)})") for k in doc if k not in MANIFEST_KEYS]
    if "search" in doc and doc["search"] not in SEARCH:
        out.append(issue("warning", "archive.bad-search", rel, "search",
                         f"'{doc['search']}' is not a search mode ({', '.join(SEARCH)}); searches use all"))
    if "prefix" in doc and not valid_prefix(doc["prefix"]):
        out.append(issue("warning", "archive.bad-prefix", rel, "prefix",
                         f"'{doc['prefix']}' is not a valid id prefix; collections use their own names"))
    for n in doc.get(resources.OFF_KEY) or []:
        if n not in resources.SWITCHABLE:
            out.append(issue("warning", "archive.bad-default", rel, resources.OFF_KEY,
                             f"'{n}' cannot be switched off (only {', '.join(resources.SWITCHABLE)}); ignored"))
    if "subject" in doc and not isinstance(doc["subject"], dict):
        out.append(issue("warning", "archive.bad-subject", rel, "subject",
                         "must be a mapping such as {label: \"Heisenberg Organization\", type: Organization}; ignored"))
    return out


# the folders an archive kept at its top level before they moved into .hydra/
OLD_LAYOUT = ("rules", "schema", "sources", "resources", "parsed")


def _old_layout(root: Path) -> list[dict]:
    """A folder the old layout kept beside collections/ is never read: its rules,
    decisions or media would be lost without a word. Rules are an error."""
    return [issue("error" if name == "rules" else "warning", "layout.old-folder", f"{name}/", "",
                  f"not read: hydra reads {layout.INTERNAL}/{name}/" +
                  ("; the last build is rebuilt there, so this one can be deleted" if name == "parsed"
                   else "; move what you need there"))
            for name in OLD_LAYOUT if (root / name).is_dir()]


def _positions(generic, declared) -> list[dict]:
    out = []
    for rel, doc in ((layout.DEFAULT_POSITIONS, generic), (layout.POSITIONS, declared)):
        if doc is None:
            continue
        if not isinstance(doc, dict):
            out.append(issue("error", "positions.shape", rel, "", "must be a mapping; ignored"))
            continue
        for name, d in rules._positions_of(doc).items():
            if d is not None:
                out += _shape(PositionModel, d, rel, "positions.shape", f"{name}.")
            if isinstance(d, dict) and d.get("outside") and (d.get("below") or d.get("above")):
                out.append(issue("warning", "positions.outside-with-relations", rel, name,
                                 "`outside: true` never takes part in placement; its below/above do nothing"))
    titles: dict[str, list[str]] = {}
    compiled = rules.compile_rules(generic if isinstance(generic, dict) else None,
                                   declared if isinstance(declared, dict) else None)["positions"]
    for name, d in compiled.items():
        for t in [name] + list(d.get("titles") or []):
            owners = titles.setdefault(norm_text(t), [])
            if name not in owners:
                owners.append(name)
    for t, owners in sorted(titles.items()):
        if t and len(owners) > 1:
            out.append(issue("warning", "positions.title-twice", layout.POSITIONS, t,
                             f"title '{t}' maps to {owners}; the first, {owners[0]}, wins"))
    return out


def _prop_names() -> set[str]:
    return {p for s in schema.SCHEMA for p in schema.resolve(s)["props"]}


def _hints(root: Path, doc, generic, declared, direction) -> list[dict]:
    rel = layout.HINTS
    if doc is None:
        return []
    if not isinstance(doc, dict):
        return [issue("error", "hints.shape", rel, "", "must be a mapping with a `hints:` list; ignored")]
    out = [issue("error", "hints.id-keyed", rel, k, "id-keyed entries are no longer read; write a "
                 "`match:` rule") for k in doc if k != "hints"]
    out += _shape(HintsFile, {"hints": doc.get("hints") or []}, rel, "hints.shape")
    positions = rules.compile_rules(generic if isinstance(generic, dict) else None,
                                    declared if isinstance(declared, dict) else None,
                                    direction=direction)["positions"]
    props = _prop_names()
    for i, h in enumerate(doc.get("hints") or []):
        if not isinstance(h, dict):
            continue
        where = f"hints[{i}]"
        when = rules.rule_when(h)
        if not when or not rules.rule_set(h):
            out.append(issue("error", "hints.incomplete", rel, where,
                             "needs `match:` and `set:` (position, badge, thumb, portrait or logo); skipped"))
            continue
        for p in rules.bad_patterns(when):
            out.append(issue("error", "hints.bad-regex", rel, where,
                             f"'{p}' is not a valid regular expression; rule skipped"))
        for k, v in _match_terms(h.get("match") or {}):
            if k == "schema" and v not in schema.SCHEMA:
                out.append(issue("warning", "hints.unknown-schema", rel, where, f"no schema '{v}'"))
            elif k == "position" and v not in positions:
                out.append(issue("warning", "hints.unknown-position", rel, where, f"no position '{v}'"))
            elif k == "linked_by" and v not in schema.SCHEMA:
                out.append(issue("warning", "hints.unknown-schema", rel, where, f"no schema '{v}'"))
            elif k == "titled":
                if not (isinstance(v, (str, list)) or (isinstance(v, dict) and "contains" in v)):
                    out.append(issue("error", "hints.bad-titled", rel, where,
                                     "`titled:` takes a title, a list of titles or {contains: pattern}"))
            elif k not in ("schema", "position", "linked_by", "any"):
                for name in str(k).split("|"):
                    if name.strip() not in props:
                        out.append(issue("warning", "hints.unknown-property", rel, where,
                                         f"no schema has a property '{name.strip()}'"))
        eff = rules.rule_set(h)
        if eff.get("position") and rules.uses_titled(when):
            out.append(issue("error", "hints.titled-position", rel, where,
                             "a `titled:` rule is display only and never sets a position; position ignored"))
        base = (root / layout.RESOURCES_DIR).resolve()
        for k in rules.IMAGES:
            path = eff.get(k)
            if not path or "://" in str(path):
                continue
            f = (base / str(path)).resolve()
            if not f.is_relative_to(base):
                out.append(issue("error", "hints.media-outside", rel, where,
                                 f"{k} '{path}' points outside {layout.RESOURCES_DIR}; not shown"))
            elif not f.is_file():
                out.append(issue("info", "hints.missing-media", rel, where,
                                 f"{layout.RESOURCES_DIR}/{path} does not exist"))
    return out


def _match_terms(match: dict):
    for k, v in (match or {}).items():
        if k == "any":
            for m in v if isinstance(v, list) else []:
                yield from _match_terms(m)
        else:
            yield k, v


def _direction(doc, direction: dict) -> list[dict]:
    rel = layout.DIRECTION
    if doc is None:
        return []
    out = _shape(DirectionFile, doc, rel, "direction.shape") if isinstance(doc, dict) else \
        [issue("error", "direction.shape", rel, "", "must be a mapping")]
    props = _prop_names()
    for name in direction.get("above") or []:
        if name not in props:
            out.append(issue("warning", "direction.unknown-property", rel, f"above.{name}",
                             f"no schema has a property '{name}'"))
    for key in ("lateral", "dual", "governing", "exclude"):
        for s in direction.get(key) or []:
            if s not in schema.SCHEMA:
                out.append(issue("warning", "direction.unknown-schema", rel, f"{key}.{s}", f"no schema '{s}'"))
    for s in direction.get("edge_positions") or {}:
        if s not in schema.SCHEMA:
            out.append(issue("warning", "direction.unknown-schema", rel, f"edge_positions.{s}", f"no schema '{s}'"))
    excl = direction.get("exclude") or []
    for s in excl:
        cover = [x for x in excl if x != s and s in schema.SCHEMA and schema.is_a(s, x)]
        if cover:
            out.append(issue("info", "direction.redundant-exclude", rel, f"exclude.{s}",
                             f"already covered by {cover[0]}"))
    above = set(direction.get("above") or [])
    for s, sc in sorted(schema.SCHEMA.items()):
        e = sc.get("edge")
        if e and not sc.get("abstract") and e["source"] in above and e["target"] in above:
            out.append(issue("info", "direction.both-ends-above", rel, s,
                             f"both ends ({e['source']}, {e['target']}) are in `above`; the target, "
                             f"{e['target']}, is the parent"))
    ignore = set((doc or {}).get("ignore") or []) if isinstance(doc, dict) else set()
    lateral = set(direction.get("lateral") or [])
    for s, sc in sorted(schema.SCHEMA.items()):
        if sc.get("abstract") or sc.get("edge") or s in lateral or schema.is_a(s, "Similar") \
                or any(schema.is_a(s, x) for x in excl):
            continue
        for p in sc.get("properties") or {}:
            pd = schema.resolve(s)["props"][p]
            if pd.get("type") != "entity" or pd.get("hidden") or p in above or f"{s}.{p}" in ignore:
                continue
            out.append(issue("info", "direction.unclassified", rel, f"{s}.{p}",
                             "an entity property that is neither a parent link nor in `ignore:`"))
    return out


def _params(root: Path) -> list[dict]:
    d = root / layout.PARAMS_DIR
    if not d.is_dir():
        return []
    out = []
    for fp in sorted(d.glob("*.param.yaml")):
        rel = f"{layout.PARAMS_DIR}/{fp.name}"
        doc = _yaml(root, rel, out)
        if isinstance(doc, dict):
            out += _shape(ParamFile, doc, rel, "params.shape")
    for msg in classify.param_issues(d, schema.SCHEMA):
        name = msg.split(" ", 2)[1]
        out.append(issue("error" if "skipped" in msg else "warning", "params.reference",
                         f"{layout.PARAMS_DIR}/{name}", "", msg.split(": ", 1)[1]))
    return out


def _verdict_values(root: Path) -> list[dict]:
    out = []
    for f in vd.files(root):
        rel = f.relative_to(root).as_posix()
        doc = _yaml(root, rel, out)
        if doc is None:
            continue
        if not isinstance(doc, dict):
            out.append(issue("error", "verdicts.shape", rel, "", "must be a mapping; ignored"))
            continue
        for k, v in doc.items():
            if not vd.valid(k, v):
                out.append(issue("error", "verdicts.bad-value", rel, str(k),
                                 f"{v!r} is not a decision this key takes; ignored"))
    return out


def _collections(root: Path) -> list[dict]:
    out = []
    manifest = {}
    mp = root / layout.COLLECTIONS_MANIFEST
    if mp.is_file():
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            out.append(issue("error", "file.json", layout.COLLECTIONS_MANIFEST, "", f"not valid JSON: {e}"))
    from hydra.ingest import parse_records
    names = []
    for f in resources.record_files(root)[0]:
        names.append(f.stem)
        rel = f"{layout.COLLECTIONS_DIR}/{f.name}"
        try:
            recs = parse_records(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            out.append(issue("error", "file.json", rel, "", f"not valid JSON: {e}"))
            continue
        for r in recs:
            s = r.get("schema")
            if s not in schema.SCHEMA:
                out.append(issue("warning", "records.unknown-schema", rel, r["id"],
                                 f"no schema '{s}'; kept as a plain node"))
                continue
            props = schema.resolve(s)["props"]
            for p, vals in (r.get("properties") or {}).items():
                pd = props.get(p)
                if pd is None and p in DISPLAY_FIELDS:
                    out.append(issue("warning", "records.display-field", rel, f"{r['id']}.{p}",
                                     f"'{p}' is not read from records: images and badges are linked to "
                                     f"entities by rules in {layout.HINTS}, from the entity's own fields"))
                elif pd is None:
                    out.append(issue("info", "records.unknown-property", rel, f"{r['id']}.{p}",
                                     f"{s} has no property '{p}'; carried along, not used"))
                elif pd.get("type") == "date":
                    for v in vals:
                        if dates.bounds(v) is None:
                            out.append(issue("warning", "records.bad-date", rel, f"{r['id']}.{p}",
                                             f"'{v}' is not a date (YYYY, YYYY-MM or YYYY-MM-DD); "
                                             "treated as undated"))
    declared = (manifest.get("collections") or {}) if isinstance(manifest, dict) else {}
    chosen = resolve_prefixes(names, manifest)
    for c in names:
        t = (declared.get(c) or {}).get("prefix") if isinstance(declared.get(c), dict) else None
        if t and chosen[c] != t:
            out.append(issue("warning", "manifest.bad-prefix", layout.COLLECTIONS_MANIFEST, f"collections.{c}.prefix",
                             f"'{t}' is not a valid prefix; '{chosen[c]}' is used"))
    return out


# ---- after a build -----------------------------------------------------------


def build_issues(*, compile_issues, verdict_disagreements, verdicts, ledger, nodes, records,
                 report, duplicates, prefix_report, subject_in_hierarchy, record_count, record_guide) -> list[dict]:
    """What only a build shows."""
    out = []
    for msg in compile_issues:
        file = (layout.DEFAULT_POSITIONS if msg.startswith("generic:") else
                layout.POSITIONS if msg.startswith("declared:") else f"{layout.RULES_DIR}/")
        level = "error" if ("ignored" in msg or "no longer read" in msg or "must be a mapping" in msg) else (
            "info" if ("is now" in msg or "belongs in .hydra/rules/hints.yaml" in msg) else "warning")
        out.append(issue(level, "rules.compile", file, "", msg.split(": ", 1)[1]
                         if msg.startswith(("generic:", "declared:")) else msg))
    for msg in verdict_disagreements:
        out.append(issue("warning", "verdicts.disagree", layout.REVIEW_DIR, msg.split(":", 1)[0][8:], msg))
    rows = {e["id"] for e in ledger}
    by_id = {r["id"]: r for r in records}
    for k, v in sorted(verdicts.items()):
        if k.startswith("stub-"):                     # a graduated name: stubs.py
            if v not in schema.SCHEMA:
                out.append(issue("warning", "verdicts.bad-stub", layout.VERDICTS, k, f"no schema '{v}'; ignored"))
            elif "stub:" + k[len("stub-"):] not in by_id:
                out.append(issue("warning", "verdicts.dead-pin", layout.VERDICTS, k,
                                 "no link value names it any more; ignored"))
            continue
        if k.startswith("cap-"):
            rid = k[4:]
            rec = by_id.get(rid)
            if rec is None and rid not in nodes:
                out.append(issue("warning", "verdicts.dead-pin", layout.VERDICTS, k, f"no record '{rid}'"))
            elif v not in ((rec or {}).get("properties") or {}).get("name", []) and \
                    v not in ((nodes.get(rid) or {}).get("props") or {}).get("name", []):
                out.append(issue("warning", "verdicts.dead-pin", layout.VERDICTS, k,
                                 f"'{v}' is not one of this record's names; ignored"))
        elif k.startswith("ref-"):
            if k not in rows:
                out.append(issue("warning", "verdicts.orphan", layout.VERDICTS, k,
                                 "no reference row has this key (its record, property or value changed?)"))
            elif v != vd.NONE and v not in by_id and v not in nodes:
                out.append(issue("warning", "verdicts.dead-pin", layout.VERDICTS, k, f"no record '{v}'"))
        elif k not in rows:
            out.append(issue("warning", "verdicts.orphan", layout.VERDICTS, k,
                             "no ledger row has this key (the records it decided may have changed)"))
    for m in report.get("override_misses") or []:
        where, _, rest = m.partition(" ")
        if "no longer read" in m:
            continue                                      # reported by check() as hints.id-keyed
        if not rest:
            out.append(issue("info", "hints.no-match", layout.HINTS, where, "matches no node"))
    for r in records or []:
        if r.get("_source") and not schema.is_a(r.get("schema") or "Thing", "Document"):
            out.append(issue("warning", "sources.not-a-document", layout.SOURCE_ENTRIES, r["id"],
                             f"{r.get('schema')} in {layout.SOURCE_ENTRIES}: a source is a Document (Article, Page, ...); "
                             "put entities in collections/"))
    for e in report["ties"].get("literal_ids") or []:
        out.append(issue("warning", "records.literal-id", f"{layout.COLLECTIONS_DIR}/", f"{e['record']}.{e['prop']}",
                         f"'{e['value']}' is the id of a record this field cannot point at (wrong type); "
                         "it is resolved as a name instead"))
    for d in duplicates:
        out.append(issue("error", "records.duplicate-id", f"{layout.COLLECTIONS_DIR}/{d['dropped']}", d["id"],
                         f"also in {d['kept']}; the first record is kept, this one dropped"))
    if prefix_report:
        for c in prefix_report["collisions"]:
            out.append(issue("warning", "prefixes.collision", layout.COLLECTIONS_MANIFEST, c["id"],
                             f"collections {c['collections']} share a prefix and this id"))
        for f in prefix_report.get("fallbacks") or []:
            out.append(issue("warning", "prefixes.archive-collision", layout.COLLECTIONS_MANIFEST,
                             f"collections.{f['collection']}",
                             f"{f['collection']} shares {f['shared']} id(s) with a collection already under the "
                             f"archive's prefix; it uses its own prefix, '{f['prefix']}'"))
        for a in prefix_report["ambiguous_pointers"]:
            out.append(issue("warning", "prefixes.ambiguous-pointer", f"{layout.COLLECTIONS_DIR}/", f"{a['record']}.{a['prop']}",
                             f"'{a['value']}' is an id in {a['collections']}; left unprefixed"))
    if subject_in_hierarchy:
        out.append(issue("error", "rules.subject-misplaced", layout.POSITIONS, "subject",
                         "`subject:` belongs in hydra.yaml; ignored here"))
    if record_count > record_guide:
        out.append(issue("warning", "archive.size", f"{layout.COLLECTIONS_DIR}/", "", f"{record_count} records: archives "
                         f"above ~{record_guide:,} build slowly; consider splitting it"))
    return out


def sort(issues: list[dict]) -> list[dict]:
    """Errors first, then by file, code and place; duplicates dropped."""
    seen, out = set(), []
    for i in sorted(issues, key=lambda i: (LEVELS.index(i["level"]), i["file"], i["code"], i["where"],
                                           i["message"])):
        k = tuple(i.values())
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out
