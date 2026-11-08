"""reg.py — the compiled side of a wiki conf.

`wiki.yaml` (and `universe/wiki.yaml`, and a collection's `wiki:` override) is
declarative; a Reg is what a conf compiles into — the lookups the wiki actually
runs per page:

    reg.roles.PERSON       which schema the methods mean by "a person"
    reg.icons.token(schema)   which icon a schema draws
    reg.badges.derive(...)    the derived-badge rule table

Each scope's merged conf gets its own Reg: the base archive's, and one per
`collections:` override, so a page renders with the registry its collection asks
for. The classes mirror the `configure()` logic of `roles`, `icons` and `badges`;
the module-level registries stay as the base (archive-level) fallback.
"""
from __future__ import annotations

import re

from hydra.wiki import badges as _badges
from hydra.wiki import icons as _icons
from hydra.wiki import roles as _roles


class Roles:
    """`roles.PERSON`, `.POST`, ... for one conf: wiki.yaml `roles:` over the defaults."""

    def __init__(self, given: dict | None = None):
        given = {str(k).upper(): str(v) for k, v in (given or {}).items() if v}
        unknown = set(given) - set(_roles.DEFAULTS)
        if unknown:
            raise ValueError(f"wiki.yaml roles: unknown {sorted(unknown)}; known: {sorted(k.lower() for k in _roles.DEFAULTS)}")
        for k, v in {**_roles.DEFAULTS, **given}.items():
            setattr(self, k, v)


class IconMap:
    """`icons: {Schema: icon-name}` over the built-in table; `token` walks ancestors."""

    def __init__(self, given: dict | None = None):
        if given is not None and not isinstance(given, dict):
            raise ValueError("wiki.yaml icons: must be a mapping of schema name to icon name")
        bad = [f"{k}: {v!r}" for k, v in (given or {}).items() if not re.fullmatch(r"[a-z0-9-]+", str(v))]
        if bad:
            raise ValueError(f"wiki.yaml icons: an icon is a file name like 'ship' (letters, digits, -): {', '.join(bad)}")
        self.override = {str(k): str(v) for k, v in (given or {}).items()}

    def token(self, schema: str) -> str:
        """The icon name for a page type: this conf's override, else the built-in, on the type or its ancestor."""
        from hydra import schema as hschema
        chain = hschema.ancestors(schema) or (schema,)
        return next((self.override[n] for n in chain if n in self.override), None) or \
            next((_icons.SCHEMA_ICON[n] for n in chain if n in _icons.SCHEMA_ICON), "")


class BadgeRules:
    """The derived-badge rule table for one conf: `badge_rules:` over `badges.DEFAULTS`."""

    def __init__(self, given: dict | None = None, enabled=True):
        if given is not None and not isinstance(given, dict):
            raise ValueError("wiki.yaml badge_rules: must be a mapping of badge key to rule")
        rules = {k: dict(v) for k, v in _badges.DEFAULTS.items()}
        for key, spec in (given or {}).items():
            key = str(key)
            if spec is None:
                rules.pop(key, None)
                continue
            if not isinstance(spec, dict):
                raise ValueError(f"wiki.yaml badge_rules: {key}: a mapping with label, group, icon, title ...")
            if bad := set(spec) - _badges.KEYS:
                raise ValueError(f"wiki.yaml badge_rules: {key}: unknown key(s) {sorted(bad)}; known: {sorted(_badges.KEYS)}")
            if spec.get("group", rules.get(key, {}).get("group", "role")) not in _badges.GROUPS:
                raise ValueError(f"wiki.yaml badge_rules: {key}: group is one of {_badges.GROUPS}")
            merged = {**rules.get(key, {"group": "role", "label": key.replace("_", " ").capitalize()}), **spec}
            if "title" not in merged and not merged.get("ongoing"):
                raise ValueError(f"wiki.yaml badge_rules: {key}: give `title` (a regular expression) or `ongoing: true`")
            rules[key] = merged
        self.rules = rules
        self.compiled = {}
        for key, r in rules.items():
            if r.get("title"):
                try:
                    self.compiled[key] = re.compile(r["title"], re.I)
                except re.error as e:
                    raise ValueError(f"wiki.yaml badge_rules: {key}: title is not a valid regular expression: {e}")
        self.enabled = enabled is not False

    def tone(self, key: str) -> str:
        return _badges.ROLE_TONE.get(key) or _badges.GROUP_TONE.get(self.rules[key]["group"], "")

    def derive(self, wiki, p, c) -> list[str]:
        """The badge keys a page earns, in rule order. Empty for anything but a person."""
        if not self.enabled or p["schema"] != c.reg.roles.PERSON:
            return []
        posts, other, ongoing = _badges._texts(wiki, p, c)
        got = {"now"} if ongoing and "now" in self.rules else set()
        role_keys = [k for k, r in self.rules.items() if r["group"] == "role" and r.get("title")]
        for t in posts:                                  # each post is one role: the first rule that fits it
            t = _badges._scrub(t)
            first = next((k for k in role_keys if self.compiled[k].search(t)), None)
            if first:
                got.add(first)
        for k, r in self.rules.items():                  # service and industry: any title or occupation
            if r["group"] != "role" and r.get("title") and any(self.compiled[k].search(_badges._scrub(t)) for t in posts + other):
                got.add(k)
        return [k for k in self.rules if k in got]


class IdentifierMap:
    """`identifiers: {ns: {label, url}}` — how an `upstream: ns:key` value names the outside site.
    The url template takes `{id}` for the key's own id; `ns: null` drops a built-in."""

    DEFAULTS = {"wikidata": {"label": "Wikidata", "url": "https://www.wikidata.org/wiki/{id}"}}

    def __init__(self, given: dict | None = None):
        if given is not None and not isinstance(given, dict):
            raise ValueError("wiki.yaml identifiers: must be a mapping of namespace to {label, url}")
        merged = dict(self.DEFAULTS)
        for ns, d in (given or {}).items():
            if d is None:
                merged.pop(str(ns), None)
                continue
            if not isinstance(d, dict) or "{id}" not in str(d.get("url") or ""):
                raise ValueError(f"wiki.yaml identifiers: {ns}: needs a url template containing {{id}}")
            merged[str(ns)] = d
        self.map = {ns: {"label": str(d.get("label") or ns.capitalize()), "url": d["url"]}
                    for ns, d in merged.items()}

    def link(self, value: str):
        """`ns:key` -> (label, url) for a namespace this conf knows, else None."""
        ns, _, key = str(value).partition(":")
        d = self.map.get(ns)
        return (d["label"], d["url"].format(id=key)) if d and key else None


class Reg:
    """The compiled lookups for one scope's merged wiki conf."""

    def __init__(self, conf: dict):
        self.conf = conf or {}
        self.roles = Roles(self.conf.get("roles"))
        self.icons = IconMap(self.conf.get("icons"))
        self.badges = BadgeRules(self.conf.get("badge_rules"), self.conf.get("derived_badges", True))
        self.identifiers = IdentifierMap(self.conf.get("identifiers"))
