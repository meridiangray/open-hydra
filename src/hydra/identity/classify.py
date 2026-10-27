"""Layer 2: each property's role, from its FTM type, then the param file.

    match    the type is identifier, name, email, phone, url or iban
    distinct the type is identifier, date, country or iban
    fold     the type is entity

Three exclusions apply to match/distinct only, before any param file:
upstream's `matchable: false` (except on name-typed properties, so `weakAlias`
stays a matcher), `hidden: true`, and date properties named `...At` (pipeline
timestamps such as `retrievedAt`). `fold` is never suppressed: whether a value
points at another record is structural.

`<Type>.param.yaml` is applied last: each category it lists replaces the
computed set for that category, so a property can be promoted or demoted. A
schema with no param file classifies from the defaults alone. The flags are
computed the same way for every schema; merge acts on match/distinct, fold on
fold."""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


from hydra import schema, yamlcache
from hydra.identity import types


@dataclass(frozen=True)
class PropertyClass:
    prop: str
    ftm_type: str
    range: str | None       # only set when ftm_type == "entity"
    match: bool
    distinct: bool
    fold: bool


_MATCH_TYPES = {"identifier", "name", "email", "phone", "url", "iban"}
_DISTINCT_TYPES = {"identifier", "date", "country", "iban"}


def default_category(ftm_type: str) -> tuple[bool, bool, bool]:
    """(match, distinct, fold) implied by `type` ALONE — the pure formula,
    before the exclusions in this module's docstring or any param.yaml
    override. Exposed separately because it's useful on its own (and
    trivially testable on its own), but `classify()` is what callers want."""
    return (ftm_type in _MATCH_TYPES, ftm_type in _DISTINCT_TYPES, ftm_type == "entity")


def _is_pipeline_metadata(prop: str, pdef: dict) -> bool:
    """The three match/distinct exclusions (see the module docstring). `matchable:
    false` is not applied to name-typed properties: `weakAlias` is the only one
    upstream marks that way, and excluding it would stop alias matching on every
    schema without a param file."""
    if pdef.get("matchable") is False and pdef.get("type") != "name":
        return True
    if pdef.get("hidden"):
        return True
    if pdef.get("type") == "date" and prop.endswith("At") and not prop.endswith("Date"):
        return True
    return False


def load_overrides(params_dir: str | Path, schema_name: str) -> dict:
    """Read `<params_dir>/<schema_name>.param.yaml` if present; {} if not.
    Shape: {match: [prop,...]?, distinct: [prop,...]?, fold: [prop,...]?} —
    each key, if present, REPLACES the default set for that category rather
    than only adding to it (so a field can be explicitly demoted)."""
    path = Path(params_dir) / f"{schema_name}.param.yaml"
    if not yamlcache.is_file(path):
        return {}
    doc = yamlcache.load(path) or {}
    return {k: list(doc[k]) for k in ("match", "distinct", "fold") if k in doc}


class PropMap(dict):
    """{prop: PropertyClass}, plus `md`: the match/distinct properties in schema
    order, computed once (a merge compares millions of pairs over these)."""

    @property
    def md(self) -> list[tuple[str, PropertyClass]]:
        if "_md" not in self.__dict__:
            self.__dict__["_md"] = [(p, pc) for p, pc in self.items() if pc.match or pc.distinct]
        return self.__dict__["_md"]

    @property
    def token_safe(self) -> bool:
        """True when every match property is a name, address or exact-value type:
        two records of this class can then only match through a word-subset or an
        equal exact value (see match.may_match)."""
        if "_safe" not in self.__dict__:
            self.__dict__["_safe"] = all(pc.ftm_type in types.TOKEN_TYPES | types.EXACT_TYPES
                                         for pc in self.values() if pc.match)
        return self.__dict__["_safe"]


_CACHE: dict[tuple, dict[str, PropertyClass]] = {}
_FROZEN: dict[str, dict] = {}       # params dir -> {file name: stamp}, during one pass


@contextmanager
def frozen_params(params_dir):
    """Read every param file's stamp once and reuse it until the block ends: a
    merge or fold pass classifies hundreds of times, and the files cannot
    change under it. Outside a block, each classify() checks its file again."""
    if not params_dir or str(params_dir) in _FROZEN:
        yield
        return
    stamps = {}
    for e in os.scandir(params_dir) if Path(params_dir).is_dir() else ():
        if e.name.endswith(".param.yaml") and e.is_file():
            st = e.stat()
            stamps[e.name] = (str(Path(params_dir) / e.name), st.st_size, st.st_mtime_ns)
    _FROZEN[str(params_dir)] = stamps
    try:
        yield
    finally:
        _FROZEN.pop(str(params_dir), None)


def _param_stamp(params_dir, schema_name: str):
    if not params_dir:
        return None
    frozen = _FROZEN.get(str(params_dir))
    if frozen is not None:
        name = f"{schema_name}.param.yaml"
        return frozen.get(name) or (str(Path(params_dir) / name), None)
    fp = Path(params_dir) / f"{schema_name}.param.yaml"
    try:
        st = fp.stat()
    except FileNotFoundError:
        return (str(fp), None)
    return (str(fp), st.st_size, st.st_mtime_ns)


def classify(schema_name: str, params_dir: str | Path | None = None) -> dict[str, PropertyClass]:
    """schema name -> {prop: PropertyClass}. Defaults from `schema.resolve()`
    type/range with the three pipeline-metadata exclusions above, then
    `<schema_name>.param.yaml` applied as a diff if `params_dir` is given.
    This is the function Layer 3/4/5 call; nothing downstream reads
    param.yaml or raw schema property dicts directly. Cached per loaded
    schema and param-file stamp: a param file is parsed again only when it
    changes, not once per record."""
    schema.ensure()
    key = (schema.LOADED.get("key"), schema_name, _param_stamp(params_dir, schema_name))
    if key[0] is not None and key in _CACHE:
        return PropMap(_CACHE[key])
    out = _classify(schema_name, params_dir)
    if key[0] is not None:
        _CACHE[key] = out
    return PropMap(out)


def _classify(schema_name: str, params_dir: str | Path | None = None) -> dict[str, PropertyClass]:
    props = schema.resolve(schema_name)["props"]
    out: dict[str, PropertyClass] = {}
    for prop, pdef in props.items():
        ftm_type = pdef.get("type", "string")
        match, distinct, fold = default_category(ftm_type)
        if _is_pipeline_metadata(prop, pdef):
            # match/distinct noise only -- `fold` is a structural fact (this
            # value literally references another entity) and must never be
            # suppressed by a display/identity-matching concern. Real case:
            # Document.ancestors is entity-typed + hidden=true; it must stay
            # fold=True (see test_schema_coverage.py's regression guard).
            match = distinct = False
        out[prop] = PropertyClass(
            prop=prop, ftm_type=ftm_type,
            range=pdef.get("range") if ftm_type == "entity" else None,
            match=match, distinct=distinct, fold=fold)

    overrides = load_overrides(params_dir, schema_name) if params_dir else {}
    for cat, wanted in overrides.items():
        wanted_set = {p for p in wanted if p in out}   # unknown names: see param_issues()
        for prop, pc in out.items():
            replace = {"match": pc.match, "distinct": pc.distinct, "fold": pc.fold}
            replace[cat] = prop in wanted_set
            out[prop] = PropertyClass(prop=pc.prop, ftm_type=pc.ftm_type, range=pc.range,
                                      **replace)
    return out


def param_issues(params_dir, schema_names) -> list[str]:
    """Problems in the param files, reported instead of stopping the build: a
    file for a schema that does not exist, a `schema:` field that disagrees
    with the file name, and property names the schema does not have (those
    are skipped by classify())."""
    if not params_dir or not Path(params_dir).is_dir():
        return []
    issues = []
    for fp in sorted(Path(params_dir).glob("*.param.yaml")):
        name = fp.name[:-len(".param.yaml")]
        doc = yamlcache.load(fp) or {}
        if name not in schema_names:
            issues.append(f"params: {fp.name} names no schema in this archive")
            continue
        if doc.get("schema") not in (None, name):
            issues.append(f"params: {fp.name} says `schema: {doc.get('schema')}`")
        props = schema.resolve(name)["props"]
        for cat in ("match", "distinct", "fold"):
            unknown = [p for p in doc.get(cat) or [] if p not in props]
            if unknown:
                issues.append(f"params: {fp.name} {cat} lists {unknown}, not properties of {name}; skipped")
    return issues
