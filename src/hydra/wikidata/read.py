"""read.py — Wikidata items + the map -> FtM records.

    convert(items, qids, rules) -> (records, report)

`items` are as `api.fetch` returns them. Each asked-for item becomes a record whose `upstream` is its
key (`wikidata:Q42`), so hydra merges it with any record that holds the key. A claim the map turns into
a relationship (Family, Membership...) becomes a record of its own, and the item at its other end a
stub with the same key. The report:

    mapped      {(P…, "Person.birthDate" | "Family"): {count, examples}}   what was copied or made
    left_out    {why: {count, examples}}                                   what could not be read
    unread      {(schema, P…): {items, claims, example}}                   claims the map has no rule for
"""
from __future__ import annotations

import re

from hydra import schema
from hydra.wikidata.api import label

URL = "https://www.wikidata.org/wiki/{}"
CIRCA = "Q5727902"                       # "circa", as a P1480 qualifier on a claim
PID = re.compile(r"^P\d+$")


def usable(item, pid) -> list[dict]:
    """The claims of a property that may be read: with a value, not deprecated, and only the preferred
    ones when there are any."""
    claims = [c for c in (item.get("claims") or {}).get(pid, [])
              if c.get("rank") != "deprecated" and c["mainsnak"].get("snaktype") == "value"]
    return [c for c in claims if c.get("rank") == "preferred"] or claims


def time_value(value) -> tuple[str | None, str | None]:
    """A Wikidata time -> (FtM date, approx kind). Precision 11 is a day, 10 a month, 9 a year, 8 a decade
    (kept as its first year, kind `decade`); anything vaguer, and any year before 1, is (None, None)."""
    m = re.match(r"^([+-])(\d+)-(\d\d)-(\d\d)", value.get("time", ""))
    if not m or m.group(1) == "-":
        return None, None
    year, month, day = m.group(2).zfill(4), m.group(3), m.group(4)
    precision = value.get("precision", 0)
    if precision >= 11 and month != "00" and day != "00":
        return f"{year}-{month}-{day}", None
    if precision == 10 and month != "00":
        return f"{year}-{month}", None
    if precision == 9:
        return year, None
    if precision == 8:
        return year[:3] + "0", "decade"
    return None, None


class Reader:
    def __init__(self, items: dict, rules: dict):
        schema.ensure()
        self.items, self.rules = items, rules
        self.mapped: dict[tuple, dict] = {}
        self.left_out: dict[str, dict] = {}
        self.unread: dict[tuple, dict] = {}

    # -- the report
    def _tally(self, table: dict, key, example: str = "") -> dict:
        row = table.setdefault(key, {"count": 0, "examples": []})
        row["count"] += 1
        if example and len(row["examples"]) < 3:
            row["examples"].append(example)
        return row

    def _name(self, q) -> str:
        return label(self.items.get(q)) or q

    # -- one value
    def value(self, snak, ftype, spec, where) -> tuple[str | None, str | None]:
        """A claim's value as a field of this type takes it -> (string, approx kind), or (None, None)."""
        dv = snak.get("datavalue") or {}
        kind, v = dv.get("type"), dv.get("value")
        if ftype == "date":
            if kind != "time":
                return None, None
            d, approx = time_value(v)
            if d is None:
                self._tally(self.left_out, "dates too vague to keep", f"{where}: {v['time'].lstrip('+')[:10]}")
            return d, approx
        if kind == "wikibase-entityid":
            return self._item_value(v["id"], ftype, spec, where), None
        if kind == "string":
            return v, None
        if kind == "monolingualtext":
            return (v["text"] if v.get("language") == "en" else None), None
        if kind == "quantity":
            return v["amount"].lstrip("+"), None
        return None, None

    def _item_value(self, q, ftype, spec, where) -> str | None:
        ref = self.items.get(q)
        if ftype in ("country", "language"):
            code = (usable(ref or {}, "P297" if ftype == "country" else "P220") or [None])[0]
            if code is None:
                plural = "countries" if ftype == "country" else "languages"
                self._tally(self.left_out, f"{plural} with no ISO code", f"{where}: {self._name(q)}")
                return None
            return code["mainsnak"]["datavalue"]["value"].lower() if ftype == "country" \
                else code["mainsnak"]["datavalue"]["value"]
        if spec.get("values"):
            word = spec["values"].get(q)
            if word is None:
                self._tally(self.left_out, "values the map does not list", f"{where}: {q} {self._name(q)}")
            return word
        return label(ref) or None

    @staticmethod
    def _circa(claim) -> bool:
        return any(((s.get("datavalue") or {}).get("value") or {}).get("id") == CIRCA
                   for s in (claim.get("qualifiers") or {}).get("P1480", []))

    # -- one item
    def schema_of(self, item) -> str | None:
        for c in usable(item, "P31"):
            cls = self.rules["classes"].get(c["mainsnak"]["datavalue"]["value"]["id"])
            if cls:
                return cls
        return None

    def stub(self, q, sname) -> dict:
        return {"id": q, "schema": sname,
                "properties": {"name": [self._name(q)], "upstream": [f"wikidata:{q}"], "sourceUrl": [URL.format(q)]}}

    def read(self, q) -> list[dict]:
        item = self.items.get(q)
        if not item:
            self._tally(self.left_out, "items Wikidata does not have", q)
            return []
        sname = self.schema_of(item)
        if not sname:
            classes = ", ".join(self._name(c["mainsnak"]["datavalue"]["value"]["id"]) for c in usable(item, "P31"))
            self._tally(self.left_out, "items whose class the map has no schema for", f"{self._name(q)} ({classes or 'no class'})")
            return []
        rec = self.stub(q, sname)
        table = {**self.rules["common"], **(self.rules["properties"].get(sname) or {})}
        relations = self.rules["relationships"].get(sname) or {}
        self._names_and_summary(item, rec, table)
        self._fields(item, rec, table)
        out = [rec] + self._relationships(item, q, relations)
        for pid, claims in (item.get("claims") or {}).items():
            if pid in table or pid in relations or pid == "P31" or pid in self.rules["ignore"]:
                continue
            row = self.unread.setdefault((sname, pid), {"items": set(), "claims": 0, "example": ""})
            row["items"].add(q)
            row["claims"] += len(claims)
            row["example"] = row["example"] or self.show(claims[0]["mainsnak"])
        return out

    def _names_and_summary(self, item, rec, table) -> None:
        props = rec["properties"]
        aliases = item.get("aliases") or {}
        for a in aliases.get("en", []) + aliases.get("mul", []):
            if a["value"] not in props["name"] + props.get("alias", []):
                props.setdefault("alias", []).append(a["value"])
        text = ((item.get("descriptions") or {}).get("en") or {}).get("value")
        if text and table.get("description"):
            props.setdefault(table["description"], []).append(text)

    def _fields(self, item, rec, table) -> None:
        sname, q = rec["schema"], rec["id"]
        pdefs = schema.resolve(sname)["props"]
        for pid, spec in table.items():
            if not PID.match(pid) or spec is None:
                continue
            spec = {"to": spec} if isinstance(spec, str) else spec
            field = spec["to"]
            if field not in pdefs:
                self._tally(self.left_out, "map fields the schema does not have", f"{sname}.{field}")
                continue
            for c in usable(item, pid):
                val, approx = self.value(c["mainsnak"], pdefs[field]["type"], spec, f"{q}.{field}")
                if val is None:
                    continue
                if val not in rec["properties"].setdefault(field, []):
                    rec["properties"][field].append(val)
                    self._tally(self.mapped, (pid, f"{sname}.{field}"), f"{self._name(q)}: {val}")
                if pdefs[field]["type"] == "date" and (approx or self._circa(c)):
                    rec.setdefault("_meta", {}).setdefault("approx", {})[field] = approx or "circa"

    def _relationships(self, item, q, relations) -> list[dict]:
        out, used = [], set()
        for pid, spec in relations.items():
            for c in usable(item, pid):
                v = (c["mainsnak"].get("datavalue") or {}).get("value")
                other = v.get("id") if isinstance(v, dict) else None
                if not other or not label(self.items.get(other)):
                    if other:
                        self._tally(self.left_out, "relationship ends with no label", f"{self._name(q)} {pid} {other}")
                    continue
                props = {k: [tpl.replace("{self}", q).replace("{value}", other)]
                         for k, tpl in spec.items() if k not in ("schema", "target", "dates")}
                meta = {}
                for qualifier, field in (spec.get("dates") or {}).items():
                    for s in (c.get("qualifiers") or {}).get(qualifier, []):
                        dv = s.get("datavalue")
                        d, approx = time_value(dv["value"]) if dv and dv.get("type") == "time" else (None, None)
                        if d:
                            props.setdefault(field, []).append(d)
                            if approx:
                                meta.setdefault("approx", {})[field] = approx
                rid, n = f"{q}-{pid}-{other}", 2
                while rid in used:
                    rid, n = f"{q}-{pid}-{other}-{n}", n + 1   # two claims, one (q, pid, other): both kept
                used.add(rid)
                rec = {"id": rid, "schema": spec["schema"], "properties": props}
                if meta:
                    rec["_meta"] = meta
                out += [rec, self.stub(other, spec["target"])]
                self._tally(self.mapped, (pid, spec["schema"]), f"{self._name(q)} → {self._name(other)}")
        return out

    def show(self, snak) -> str:
        """A claim's value as a reader sees it, for an example."""
        dv = snak.get("datavalue") or {}
        kind, v = dv.get("type"), dv.get("value")
        if kind == "wikibase-entityid":
            return self._name(v["id"])
        if kind == "time":
            return v["time"].lstrip("+")[:10]
        if kind == "monolingualtext":
            return v["text"]
        if kind == "quantity":
            return v["amount"].lstrip("+")
        return str(v)[:60] if v is not None else ""


def convert(items: dict, qids, rules: dict) -> tuple[list[dict], dict]:
    reader = Reader(items, rules)
    merged: dict[str, dict] = {}
    for q in qids:
        for i, rec in enumerate(reader.read(q)):
            if rec["id"] not in merged or (i == 0 and rec["id"] == q):   # an item asked for beats the stub another made
                merged[rec["id"]] = rec
    return list(merged.values()), {"mapped": reader.mapped, "left_out": reader.left_out, "unread": reader.unread}
