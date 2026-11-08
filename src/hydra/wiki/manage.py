"""manage.py — look at, and change, how an archive's wiki is laid out (`hydra-ctl wiki edges | sections | define | undefine`).

`edges`     what the pages hold: every (page type, relationship, side) with a count, and what draws it
            (a built-in section, a section defined in wiki.yaml, or the default list of other relationships)
`sections`  the built-in sections, the ones wiki.yaml defines, and what each page type gets, in order
`define`    add a section to wiki.yaml (checked before anything is written) and, with `schemas`, to those page types
`undefine`  take a defined section out of wiki.yaml, and out of any `sections:` list that names it

wiki.yaml is rewritten whole by these. A file that carries comments is refused unless `force` is set, and then
the old one is kept as wiki.yaml.bak.
"""
from __future__ import annotations

import re
import shutil
from collections import Counter
from pathlib import Path

import yaml

from hydra.wiki import badges, declared, views

FILE = "wiki.yaml"
BUILTIN_EDGES = lambda w: {w.reg.roles.OWNERSHIP, w.reg.roles.REPRESENTATION}


def drawn_by(w, schema: str, edge: str, side: str) -> str:
    """What draws (edge, side) on a page of this type: `built-in`, `defined: <name>`, or `default list`."""
    for m in views.methods_for(schema, w.conf):
        if getattr(m, "declared", False) and (edge, side) in getattr(m, "covers", lambda reg=None: set())(w.reg):
            return f"defined: {m.__name__}"
    if (edge, side) in w.handled(schema, w.reg) or edge in BUILTIN_EDGES(w):
        return "built-in"
    return "default list"


def edges(w) -> list[dict]:
    """[{schema, edge, side, count, other, shown_by}] over the listed pages, most used first."""
    n, others = Counter(), {}
    for p in w.pages.values():
        for r in p["relations"]:
            k = (p["schema"], r.get("edge"), r.get("side"))
            n[k] += 1
            o = (w.pages.get(r.get("other")) or {}).get("schema")
            if o:
                others.setdefault(k, Counter())[o] += 1
    return [{"schema": s, "edge": e, "side": d, "count": c, "other": ", ".join(x for x, _ in others.get((s, e, d), Counter()).most_common(3)),
             "shown_by": drawn_by(w, s, e, d)} for (s, e, d), c in sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))]


def sections(w) -> dict:
    """{"builtin": [names], "defined": {name: spec}, "by_schema": {schema: [names]}} for the schemas the pages use."""
    defined = {n: s for n, s in (w.conf.get("define") or {}).items()}
    builtin = sorted(n for n, f in views.SECTIONS.items() if not getattr(f, "declared", False))
    schemas = sorted({p["schema"] for p in w.pages.values()})
    return {"builtin": builtin, "defined": defined,
            "by_schema": {s: [m.__name__ for m in views.methods_for(s, w.conf)] for s in schemas}}


def badge_report(w) -> list[dict]:
    """[{key, label, group, icon, pages, examples}] for each derived-badge rule, most pages first."""
    from hydra.wiki import views as v
    hit: dict[str, list] = {k: [] for k in w.reg.badges.rules}
    for b, p in w.pages.items():
        if b not in w.listed:
            continue
        for k in badges.derive(w, p, v.Ctx(w, None, p)):
            hit.setdefault(k, []).append(w.title(b))
    return sorted(({"key": k, "label": r.get("label", k), "group": r["group"], "icon": r.get("icon", ""),
                    "rule": "an open post" if r.get("ongoing") else r["title"], "pages": len(hit.get(k, [])), "examples": hit.get(k, [])[:3]}
                   for k, r in w.reg.badges.rules.items()), key=lambda x: -x["pages"])


# ------------------------------------------------------------------------------------------ wiki.yaml

def read(root) -> tuple[dict, str]:
    f = Path(root) / FILE
    text = f.read_text(encoding="utf-8") if f.is_file() else ""
    doc = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(doc, dict):
        raise SystemExit(f"hydra: {f} is not a mapping; fix it by hand first")
    return doc, text


def write(root, doc: dict, text: str, force: bool) -> None:
    f = Path(root) / FILE
    if re.search(r"^\s*#", text, re.M) and not force:
        raise SystemExit(f"hydra: {f} has comments, which a rewrite would lose; add --force to rewrite it "
                         f"(the old one is kept as {FILE}.bak), or edit it by hand")
    if text and force:
        shutil.copyfile(f, f.with_name(FILE + ".bak"))
    f.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def _insert(names: list[str], name: str) -> list[str]:
    """`name` into a section list, before `recorded` (which closes a page) when it has one."""
    if name in names:
        return names
    return [*names[:names.index("recorded")], name, *names[names.index("recorded"):]] if "recorded" in names else [*names, name]


def define(root, w, name: str, spec: dict, schemas: list[str], force: bool = False) -> list[str]:
    """Add `name` to wiki.yaml `define:` (replacing one of that name) and to each of `schemas`' section lists.
    Checked first: a bad definition writes nothing. -> what was changed, in words."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise SystemExit(f"hydra: a section name is lower case letters, digits and _ (got {name!r})")
    try:
        declared.build(name, spec)
    except ValueError as err:
        raise SystemExit(f"hydra: {err}")
    if name in views.SECTIONS and not getattr(views.SECTIONS[name], "declared", False):
        raise SystemExit(f"hydra: {name} is a built-in section; pick another name")
    doc, text = read(root)
    said = [f"{'replaced' if name in (doc.get('define') or {}) else 'defined'} {name}"]
    doc.setdefault("define", {})[name] = spec
    for s in schemas:
        cur = (doc.get("sections") or {}).get(s) or [m.__name__ for m in views.methods_for(s, w.conf)]
        doc.setdefault("sections", {})[s] = _insert(list(cur), name)
        said.append(f"added to {s} pages")
    write(root, doc, text, force)
    return said


def undefine(root, name: str, force: bool = False) -> list[str]:
    doc, text = read(root)
    if name not in (doc.get("define") or {}):
        raise SystemExit(f"hydra: no section {name!r} is defined in {FILE}")
    del doc["define"][name]
    if not doc["define"]:
        del doc["define"]
    said = [f"removed {name}"]
    for s, names in list((doc.get("sections") or {}).items()):
        if name in (names or []):
            doc["sections"][s] = [x for x in names if x != name]
            said.append(f"taken out of {s} pages")
    write(root, doc, text, force)
    return said
