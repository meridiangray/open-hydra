"""importmap.py — `import --map FILE.yaml`: an export's habits, mapped to hydra's shape once.

Exports often put facts where hydra cannot read them: in `notes` lines
("House: Al Saud"), in names ("Saud bin Abdulaziz (son of ...)", "... #2"), in
dates ("c. 1748"), and in links written as names. A map says, once per source,
what each habit means; the import rewrites the records and reports every change.

    links: ids                  # a link naming exactly one record of the file is written as its id
    names:
      qualifiers: description   # "Name (son of X)" -> name "Name", description "son of X";
                                # "Name #2" -> "Name" (the ids keep the two apart)
    notes:                      # one rule per "Key: value" line in `notes`
      Source: {property: sourceUrl}          # the value (urls in [...] unwrapped) into a property
      Born:   {property: birthDate}          # a date: "c. 1748" keeps its qualifier (see dates.approx)
      House:                                 # the value as a relationship to an entity made once
        create: {schema: Organization, name: "House of {value}"}
        link:   {schema: Membership, member: "{record}", organization: "{created}", role: house}
    keep_notes: true            # the lifted lines stay in notes too (the record as the source wrote it)

Date properties always keep approximate dates as their date plus `_meta.approx`.
Links are made ids before names are cleaned, so a cleaned name never moves a link.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from hydra import dates, schema

NOTE_LINE = re.compile(r"^\s*([A-Z][A-Za-z ]{0,40}?)\s*:\s*(.+?)\s*$")
QUALIFIER = re.compile(r"^(.*?)\s*\((.+)\)\s*$")
NUMBERED = re.compile(r"^(.*?)\s+#\d+$")
URL_IN = re.compile(r"\[?(https?://[^\s\]]+)\]?")


def _fill(template, **values):
    if isinstance(template, str):
        return template.format(**values)
    return template


def _id(*parts) -> str:
    return "map-" + hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]


def apply(records: list[dict], spec: dict) -> tuple[list[dict], dict]:
    """-> (records, report {what: count, examples: {...}})."""
    schema.ensure()
    spec = spec or {}
    out = [dict(r, properties={k: list(v) for k, v in (r.get("properties") or {}).items()}) for r in records]
    report, examples = Counter(), {}

    def note(kind, text):
        report[kind] += 1
        examples.setdefault(kind, [])
        if len(examples[kind]) < 3:
            examples[kind].append(text)

    # 1. links naming exactly one record of the file -> its id (before any name changes)
    if spec.get("links") == "ids":
        names = {}
        for r in out:
            for v in r["properties"].get("name") or []:
                names.setdefault(v, set()).add(r["id"])
        for r in out:
            pdefs = schema.resolve(r["schema"])["props"] if r.get("schema") in schema.SCHEMA else {}
            for p, vals in r["properties"].items():
                if (pdefs.get(p) or {}).get("type") != "entity" or p in ("sources", "proof"):
                    continue
                new = []
                for v in vals:
                    hits = names.get(v, set())
                    if len(hits) == 1 and v not in {x["id"] for x in out}:
                        new.append(next(iter(hits)))
                        note("links made ids", f"{r['id']}.{p}: {v}")
                    else:
                        if len(hits) > 1:
                            note("links left as names (several records)", f"{r['id']}.{p}: {v}")
                        new.append(v)
                r["properties"][p] = new

    # 2. names: qualifiers out of the name
    if (spec.get("names") or {}).get("qualifiers"):
        into = spec["names"]["qualifiers"]
        for r in out:
            names = r["properties"].get("name") or []
            clean = []
            for v in names:
                m = NUMBERED.match(v)
                if m:
                    note("numbered names cleaned", v)
                    v = m.group(1)
                m = QUALIFIER.match(v)
                if m and into:
                    v, q = m.group(1), m.group(2)
                    r["properties"].setdefault(into, [])
                    if q not in r["properties"][into]:
                        r["properties"][into].append(q)
                    note("qualifiers moved out of names", f"{m.group(0)} -> {v}")
                clean.append(v)
            if names:
                r["properties"]["name"] = list(dict.fromkeys(clean))

    # 3. notes lines -> properties and relationships
    rules = spec.get("notes") or {}
    keep = spec.get("keep_notes", True)
    created: dict[tuple, str] = {}
    extra = []
    for r in out:
        kept_lines = []
        for n in r["properties"].get("notes") or []:
            lines = []
            for line in n.splitlines():
                m = NOTE_LINE.match(line)
                rule = rules.get(m.group(1)) if m else None
                if not rule:
                    lines.append(line)
                    continue
                key, value = m.group(1), m.group(2)
                if rule.get("property"):
                    prop = rule["property"]
                    vals = [u for u in URL_IN.findall(value)] if prop.endswith("Url") else [value]
                    for v in vals or [value]:
                        pd = (schema.resolve(r["schema"])["props"].get(prop) or {}) if r["schema"] in schema.SCHEMA else {}
                        if pd.get("type") == "date":
                            d, kind = dates.exact(v)
                            if d is None:
                                note("note values that are no date", f"{r['id']}: {key}: {v}")
                                continue
                            v = d
                            if kind:
                                r.setdefault("_meta", {}).setdefault("approx", {})[prop] = kind
                        r["properties"].setdefault(prop, [])
                        if v not in r["properties"][prop]:
                            r["properties"][prop].append(v)
                    note(f"notes '{key}' -> {prop}", f"{r['id']}: {value}")
                if rule.get("link"):
                    target = None
                    if rule.get("create"):
                        c = {k: _fill(v, value=value, record=r["id"]) for k, v in rule["create"].items()}
                        ck = (c["schema"], c.get("name"))
                        if ck not in created:
                            created[ck] = _id("create", *ck)
                            extra.append({"id": created[ck], "schema": c.pop("schema"),
                                          "properties": {k: [v] for k, v in c.items()}})
                            note(f"notes '{key}' created", c.get("name"))
                        target = created[ck]
                    link = {k: _fill(v, value=value, record=r["id"], created=target or "") for k, v in rule["link"].items()}
                    sname = link.pop("schema")
                    extra.append({"id": _id("link", r["id"], key, value), "schema": sname,
                                  "properties": {k: [v] for k, v in link.items() if v}})
                    note(f"notes '{key}' -> {sname}", f"{r['id']}: {value}")
                if keep:
                    lines.append(line)
            text = "\n".join(lines).strip()
            if text:
                kept_lines.append(text)
        if "notes" in r["properties"]:
            r["properties"]["notes"] = kept_lines
            if not kept_lines:
                del r["properties"]["notes"]

    # 4. date properties: approximate dates kept as date + qualifier
    for r in out:
        pdefs = schema.resolve(r["schema"])["props"] if r.get("schema") in schema.SCHEMA else {}
        for p, vals in r["properties"].items():
            if (pdefs.get(p) or {}).get("type") != "date":
                continue
            fixed = []
            for v in vals:
                d, kind = dates.exact(v)
                if d is not None and kind:
                    r.setdefault("_meta", {}).setdefault("approx", {})[p] = kind
                    note("approximate dates kept", f"{r['id']}.{p}: {v}")
                fixed.append(d if d is not None else v)
            r["properties"][p] = fixed
    return out + extra, {"changes": dict(report), "examples": examples, "records_added": len(extra)}
