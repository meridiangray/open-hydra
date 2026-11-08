"""readiness.py — what keeps the wiki's pages from being complete, as things to do.

Read from the pages the universe build made and the archive build's issues;
each finding says what is missing, how much, a few examples, and what to
record (or decide) so the page fills in. Written for a person or an agent:
every `do` names the record shape, the command or the tool that fixes it.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

from hydra import layout, standards, vocab
from hydra import schema as hschema
from hydra.shape import rules
from hydra.wiki import roles
from hydra.universe import layer

def tenure(reg) -> tuple:
    """Edges that are terms: a membership (a house, a party) often has none."""
    return (reg.roles.TENURE, "Directorship", "Employment")
NOTE_LINE = re.compile(r"^\s*([A-Z][A-Za-z ]{0,40}?)\s*:\s*\S", re.M)
QUALIFIED = re.compile(r"\(.+\)\s*$|\s#\d+$")


def is_asset(schema: str) -> bool:
    """A thing that is owned rather than an owner: an Asset (a vessel, a painting, real estate) that
    is not itself a legal entity (FtM makes a Company an Asset too, but a company stands on its own)."""
    return hschema.is_a(schema, "Asset") and not hschema.is_a(schema, "LegalEntity")


def off_vocabulary(pages, vs) -> Counter:
    """`Schema.prop = 'value'` -> how often, for values a vocabulary covers but does not list."""
    props = {a.split(".", 1)[1] for a in vocab.covered(vs)}
    out = Counter()
    for p in pages:
        for r in p["relations"]:
            for prop in props:
                if r.get("side") == "source" and vocab.outside(vs, r.get("edge") or "", prop, r.get(prop)):
                    out[f"{r['edge']}.{prop} = {r[prop]!r}"] += 1
        for b in p["infobox"]:
            if b["prop"] in props:
                for v in b["values"]:
                    if vocab.outside(vs, p["schema"], b["prop"], v.get("value")):
                        out[f"{p['schema']}.{b['prop']} = {v['value']!r}"] += 1
    return out


def context_links(pages, kind: str) -> Counter:
    """A relationship's context links (its deal, contract...) that are `red` or `unresolved`, each
    relationship's once: "name (as Label)" -> how often. A relationship is on both its ends' pages,
    so it is counted from its source end, or from its target end when the source is no page."""
    out = Counter()
    for p in pages:
        for r in p["relations"]:
            if r.get("side") == "source" or not r.get("other"):
                for c in r.get("context") or ():
                    if c.get(kind):
                        out[f"{c['name']} (as {c['label']})"] += 1
    return out


def _f(code, level, items, what, do):
    items = list(items)
    return {"code": code, "level": level, "count": len(items), "what": what, "examples": items[:5], "do": do} \
        if items else None


def gaps(p, reg) -> list[tuple[str, str]]:
    """[(code, what)] this one page lacks, by the same codes `check` reports for the whole archive."""
    out = []
    if not any(c["docs"] or c["urls"] for c in p["citations"]):
        out.append(("pages.unsourced", "its records cite no document and no link"))
    if any(r.get("edge") in tenure(reg) and r.get("side") == "source"
           and not (r.get("startDate") or r.get("endDate") or r.get("date")) for r in p["relations"]):
        out.append(("terms.undated", "some of its terms have no year"))
    if p["schema"] == reg.roles.PERSON and not any(b["prop"] in ("birthDate", "deathDate") for b in p["infobox"]):
        out.append(("people.undated", "no birth or death date"))
    if p["schema"] == reg.roles.POST and not any(b["prop"] == "organization" for b in p["infobox"]):
        out.append(("posts.no-body", "no organization for the post"))
    if is_asset(p["schema"]) and not any(r.get("edge") == reg.roles.OWNERSHIP and r.get("side") == "target" for r in p["relations"]):
        out.append(("assets.no-owner", "no owner is recorded for this asset"))
    ctx = [c for r in p["relations"] for c in r.get("context") or ()]
    if any(r.get("red") for r in p["relations"]) or any(v.get("red") for b in p["infobox"] for v in b["values"]) \
            or any(c.get("red") for c in ctx):
        out.append(("links.red", "it names entries that have no record yet"))
    if any(r.get("unresolved") for r in p["relations"]) or any(c.get("unresolved") for c in ctx):
        out.append(("links.ambiguous", "it names entries that match several records"))
    return out


def check(root) -> list[dict]:
    root = Path(root)
    from hydra.wiki import conf as wconf, reg as wreg
    conf = wconf.conf_doc(root)
    from hydra.wiki import badges as dbadges, icons as wicons
    roles.configure((conf or {}).get("roles"))           # the archive's own names for person/post/event...
    base_reg = wreg.Reg(conf)
    regs = {n: wreg.Reg(c) for n, c in wconf.collection_conf(root, conf).items()}
    def reg_for(p):
        coll = (p or {}).get("collection") or ""
        names = [n for x in (coll if isinstance(coll, list) else [coll])
                 for n in (x, x.rsplit("/", 1)[-1]) if n]
        return next((regs[n] for n in names if n in regs), base_reg)
    all_regs = list({id(r): r for r in (base_reg, *regs.values())}.values())
    wicons.configure((conf or {}).get("icons"))
    dbadges.configure((conf or {}).get("badge_rules"), (conf or {}).get("derived_badges", True))
    every = layer.read_parsed(root, "pages.jsonl")
    pages = [p for p in every if (p.get("scope") or {}).get("in", True)]     # context (scope.yaml) is not counted
    context = [p for p in every if not (p.get("scope") or {}).get("in", True)]
    build = yaml.safe_load((root / layout.BUILD_YAML).read_text(encoding="utf-8")) if (root / layout.BUILD_YAML).is_file() else {}
    title = lambda p: f"{p['title']} ({p['schema']})"
    by = {p["body"]: p for p in every}
    other = lambda r: by[r["other"]]["title"] if r.get("other") in by else r.get("name", "")
    out = []

    terms = [(p, r) for p in pages for r in p["relations"]
             if r.get("edge") in tenure(reg_for(p)) and r.get("side") == "source"
             and not (r.get("startDate") or r.get("endDate") or r.get("date"))]
    out.append(_f("terms.undated", "warning", (f"{title(p)}: {r['verb']} {other(r)}" for p, r in terms),
                  "terms of office with no year",
                  "add startDate and endDate (or date) to these relationship records: YYYY, or c. YYYY, "
                  "before YYYY, after YYYY when the source is vague"))
    red = Counter(r["name"] for p in pages for r in p["relations"] if r.get("red"))
    red.update(v["value"] for p in pages for b in p["infobox"] for v in b["values"] if v.get("red"))
    red.update(context_links(pages, "red"))
    out.append(_f("links.red", "warning", (f"{n} ({c}x)" for n, c in red.most_common()),
                  "names that link to nothing (red links)",
                  "write a record for each (save it, then the links find it), or `hydra-ctl stubs graduate` "
                  "the name into one"))
    unresolved = Counter(r["name"] for p in pages for r in p["relations"] if r.get("unresolved"))
    unresolved.update(context_links(pages, "unresolved"))
    out.append(_f("links.ambiguous", "warning", (f"{n} ({c}x)" for n, c in unresolved.most_common()),
                  "names that could mean several entries",
                  "write the link as the record's id (check_records lists the candidates with their facts), "
                  "or answer the reference question (`open_questions`, kind references)"))
    pairs = (layer.read_parsed(root, "report.json").get("proposed") or [])
    out.append(_f("names.same", "info", (f"{by[a]['title']}: {by[a]['qualifier'] or '?'} / {by[b]['qualifier'] or '?'}"
                                          for a, b in pairs if a in by and b in by),
                  "pairs of entries with the same name",
                  "if they are one entity: `universe merge A B` (or pin one record `upstream: <the other's H>`); "
                  "if not: `universe reject A B`, and the hatnote goes"))
    out.append(_f("names.qualified", "warning", (p["title"] for p in pages if QUALIFIED.search(p["title"])),
                  "names with a disambiguator in them ('(son of …)', '#2')",
                  "keep the name clean and let the ids keep them apart; the wiki adds the qualifier itself "
                  "(`import --map` with names.qualifiers moves them for a whole collection)"))
    keys = Counter(m.group(1) for p in pages for n in p["notes"] for m in NOTE_LINE.finditer(n))
    out.append(_f("notes.structured", "info", (f"{k} ({c}x)" for k, c in keys.most_common() if c > 2),
                  "facts written as 'Key: value' lines in notes",
                  "record each as a property (a date, a place, a URL) or a relationship (a house or dynasty is a "
                  "Membership in an Organization); `import --map` with a notes rule does it for a collection"))
    out.append(_f("people.undated", "info",
                  (title(p) for p in pages if p["schema"] == reg_for(p).roles.PERSON
                   and not any(b["prop"] in ("birthDate", "deathDate") for b in p["infobox"])),
                  "people with no birth or death date",
                  "add birthDate / deathDate when the source gives them (c. YYYY is fine)"))
    out.append(_f("posts.no-body", "info",
                  (title(p) for p in pages if p["schema"] == reg_for(p).roles.POST
                   and not any(b["prop"] == "organization" for b in p["infobox"])),
                  "offices with no organization",
                  "add `organization` to the Position record (the body the post belongs to)"))
    out.append(_f("pages.unsourced", "warning",
                  (title(p) for p in pages if not any(c["docs"] or c["urls"] for c in p["citations"])),
                  "pages with no sources",
                  "save records with a source (save cites it for you), or add `sources` / `sourceUrl`"))
    out.append(_f("assets.no-owner", "warning", (title(p) for p in pages if is_asset(p["schema"])
                                                 and not any(r.get("edge") == reg_for(p).roles.OWNERSHIP and r.get("side") == "target" for r in p["relations"])),
                  "assets with no recorded owner",
                  "add an Ownership record (owner -> asset) with its `percentage` when the source gives one, and a source"))
    out.append(_f("ownership.no-share", "info",
                  (f"{title(p)}: {r['verb']} {other(r)}" for p in pages for r in p["relations"]
                   if r.get("edge") == reg_for(p).roles.OWNERSHIP and r.get("side") == "source" and not r.get("percentage")),
                  "ownership records with no share",
                  "add `percentage` when the source states one; leave it off when it does not"))
    odd = off_vocabulary(pages, vocab.load(root))
    out.append(_f("values.off-vocabulary", "info", (f"{k} ({c}x)" for k, c in odd.most_common()),
                  "status words not in the vocabulary",
                  f"use a listed word (`vocabularies` lists them), or add the word and what it means to "
                  f"{layout.VOCABULARIES}"))
    std = standards.load(root)
    bad = Counter()
    for p in pages:
        pdefs = hschema.resolve(p["schema"])["props"] if p["schema"] in hschema.SCHEMA else {}
        for b in p["infobox"]:
            kind = std.kind_of(p["schema"], b["prop"], (pdefs.get(b["prop"]) or {}).get("type"))
            for v in b["values"] if kind else ():
                if v.get("value") and std.valid(kind, v["value"]) is False:
                    bad[f"{p['schema']}.{b['prop']} = {v['value']!r} (no {kind} code)"] += 1
    out.append(_f("values.off-standard", "warning", (f"{k} ({c}x)" for k, c in bad.most_common()),
                  "unrecognised country, currency or language codes",
                  "write the ISO code (country `sa`, currency `SAR`, language `ara`); for a code ISO lacks, "
                  f"give its name in {layout.STANDARDS} `countries`"))
    undeclared = Counter(k["ns"] for p in pages for k in p.get("keys") or () if not k["declared"])
    out.append(_f("keys.undeclared", "info", (f"{ns} ({c}x)" for ns, c in undeclared.most_common()),
                  "key namespaces missing from keys.yaml",
                  f"declare each in {layout.KEYS} (label, url, property, unique), or correct the misspelt keys"))
    out.append(_f("keys.conflict", "warning",
                  (f"{title(p)}: {', '.join(d[4:] for d in p['disagree'] if d.startswith('key:'))}"
                   for p in pages if any(d.startswith("key:") for d in p.get("disagree") or ())),
                  "entries with two keys where only one is allowed",
                  "check which key is right and correct the record (`amend_records`), or, if they are two "
                  "entities, `universe reject` them"))
    report = layer.read_parsed(root, "report.json")
    apart = [w for w in report.get("warnings") or [] if w.startswith("key ")]
    out.append(_f("keys.kept-apart", "warning", apart,
                  "keys shared by records of different kinds",
                  "a namespace should key one kind of thing: correct the key on the wrong record"))
    from hydra import provenance
    prov = provenance.report(root, top=200)
    only = [s for s in prov["suggestions"] if s["w"] == 1.0]
    out.append(_f("sources.wikipedia", "info", (f"{s['title']} ({s['schema']}): {s['citations']} citations" for s in only),
                  "entries sourced only from Wikipedia",
                  "re-source them from what Wikipedia itself cites: hydra-mcp source_report lists the records, "
                  "wikipedia_footnotes finds each quote's references, fetch_source keeps one, swap_source replaces "
                  "the citation once the fact is quoted in that source's own words"))
    reach = rules.image_reach(root)
    hints = (yaml.safe_load((root / layout.HINTS).read_text(encoding="utf-8")) or {}).get("hints") if (root / layout.HINTS).is_file() else None
    out.append(_f("hints.unmatched", "info",
                  (f"hints[{i}] {h.get('match')} -> {h.get('set')}" for i, h in enumerate(hints or [])
                   if reach is not None and isinstance(h, dict) and any(k in (h.get("set") or {}) for k in rules.IMAGES)
                   and not reach.get(i)),
                  "image rules that match no entry",
                  "check the rule's match (`hydra-ctl hints` numbers them; a comma or colon in a name needs quotes), "
                  "or remove it"))
    used = sorted({p["schema"] for p in pages})
    from hydra.wiki import icons
    out.append(_f("icons.missing", "info", (s for s in used if all(not icons.svg(root, rg.icons.token(s)) for rg in all_regs)),
                  "page types with no icon",
                  f"give the type an icon in wiki.yaml (`icons: {{{used[0] if used else 'Type'}: ship}}`; the name is a file "
                  f"under {layout.RESOURCES_DIR}/icons/, the archive's own first)"))
    out.append(_f("scope.context", "info", (f"{p['title']} ({p['schema']})" for p in sorted(context, key=lambda p: p["title"])),
                  "entries outside this archive's scope",
                  f"if one belongs, add it to `include` in {layout.SCOPE} (an H, a key or a title), or record the "
                  "relationship that ties it in (an owner for an asset, an office for a person)"))
    facts = [i for i in build.get("issues") or [] if i.get("code", "").startswith("facts.")]
    out.append(_f("facts", "warning", (f"{i['code']}: {i['message']}" for i in facts),
                  "facts that contradict each other",
                  "check each against its source and correct the record (`amend_records`), or note why it holds"))
    return [x for x in out if x]
