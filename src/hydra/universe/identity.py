"""identity.py — which records of the universe are one entity, and which H each one is.

Identity, strongest first; a union never crosses a rejection (a row's `not`):
 1. a decided row keeps its members together
 2. a record's `upstream: H-...` pin joins it to that H
 3. a key (`upstream: ns:key`, or a property keys.yaml maps to a namespace) held by
    several records joins them, in one member or across members (compatible schemas)
 4. the same identifier value in two members (and compatible schemas)
Inside one member, its own merges stand as they are. A name in common is never
a merge: it is offered for review.

Which H a cluster gets: the strongest row anchored in it (decided before
published, then oldest); a row whose anchor landed in a cluster another row
already holds is redirected to it (flag 8). A cluster with no row gets a
computed H: from its primary key when it holds one (keys.yaml `primary`), else
from its smallest record ref. Flags, computed here and never written to the
table: 4 a decided row's members changed since the decision (or its written
redirect no longer holds), 2 its records disagree on a date or gender, or it
holds two keys of a `unique` namespace, 1 none of its records is left.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from hydra import keys as hkeys
from hydra.identity import types as htypes
from hydra.universe import hid
from hydra.universe import table as T

ID_TYPES = ("identifier", "checksum")
LIFE = ("birthDate", "deathDate")


def compatible(a: str, b: str, anc: dict) -> bool:
    return a == b or a in anc.get(b, ()) or b in anc.get(a, ())


def dates_disagree(vals) -> bool:
    vals = sorted({str(v) for v in vals})
    return any(not (y.startswith(x) or x.startswith(y)) for i, x in enumerate(vals) for y in vals[i + 1:])


class _Union:
    def __init__(self, items, rejected):
        self.parent = {x: x for x in items}
        self.rejected = rejected
        self.blocked = []

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b, why: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        for x, y in self.rejected:
            if {self.find(x), self.find(y)} == {ra, rb}:
                self.blocked.append({"a": a, "b": b, "why": why, "rejected": [x, y]})
                return False
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra
        return True


@dataclass
class Identity:
    uid: str
    members: list
    rows: dict
    ents: dict = field(default_factory=dict)            # entity ref -> (member, entity)
    ent_of_record: dict = field(default_factory=dict)   # record ref -> entity ref
    clusters: dict = field(default_factory=dict)        # cluster -> [entity refs]
    cl_records: dict = field(default_factory=dict)      # cluster -> sorted record refs
    hs: dict = field(default_factory=dict)              # body -> {state, flags, cluster, redirect, row, anchor}
    claimed: dict = field(default_factory=dict)         # cluster -> body
    h_of_entity: dict = field(default_factory=dict)     # entity ref -> body
    anchor_of: dict = field(default_factory=dict)       # cluster -> anchor record ref
    anc: dict = field(default_factory=dict)             # schema -> ancestors
    keys: dict = field(default_factory=dict)            # cluster -> sorted `ns:key`s its records hold
    keyconf: dict = field(default_factory=dict)         # keys.yaml as loaded
    warnings: list = field(default_factory=list)
    blocked: list = field(default_factory=list)

    def link(self, m, value: str):
        """A value of member `m` that names a record (its id) -> the H of that record, or None."""
        sid = m.records.get(value, value)
        return self.h_of_entity.get(m.ref(sid))

    def body_of_record(self, ref: str):
        er = self.ent_of_record.get(ref)
        return self.h_of_entity.get(er) if er else None


def assign(uid: str, members: list, rows: dict, labels=(), keyconf: dict | None = None) -> Identity:
    """Cluster the members' entities and give each cluster its H. `labels`: the names
    this universe answers to in an `upstream` pin (`label:H-...`). `keyconf`: keys.yaml."""
    live = [m for m in members if not m.problem]
    I = Identity(uid=str(uid), members=members, rows=rows,
                 keyconf=keyconf or {"namespaces": {}, "primary": []})
    I.warnings = [w for m in members for w in m.warnings] + \
                 [f"member {m.name}: {m.problem}" for m in members if m.problem]
    for m in live:
        for s, info in m.schemas.items():
            I.anc.setdefault(s, set()).update(info["ancestors"])
    for m in live:
        for sid, e in m.entities.items():         # a stub is a name with no record: a red link, not an entity
            if not (m.schemas.get(e["schema"]) or {}).get("edge") and sid not in m.stubs:
                I.ents[m.ref(sid)] = (m, e)
        for rid, sid in m.records.items():
            if m.ref(sid) in I.ents:
                I.ent_of_record[m.ref(rid)] = m.ref(sid)
    records_of = defaultdict(set)
    for rr, er in I.ent_of_record.items():
        records_of[er].add(rr)

    rejected = []
    for body, row in rows.items():
        for other in row.get("not") or []:
            o = rows.get(T.follow(rows, other))
            a, b = I.ent_of_record.get(row["anchor"]), o and I.ent_of_record.get(o["anchor"])
            if a and b:
                rejected.append((a, b))
    uf = _Union(I.ents, rejected)

    # 1. decided rows keep their members together
    for body, row in sorted(rows.items(), key=lambda kv: kv[1].get("seq", 0)):
        if row["state"] == "d" and not row.get("redirect"):
            here = [I.ent_of_record[r] for r in row.get("members") or [] if r in I.ent_of_record]
            for x in here[1:]:
                uf.union(here[0], x, f"decided H-{body}")
    # 2. upstream pins
    for m in live:
        for rid, rec in m.raw.items():
            for pin in rec.get("_upstream") or (rec.get("properties") or {}).get("upstream") or []:
                if m.ref(rid) not in I.ent_of_record:
                    continue
                if hkeys.parse(pin):
                    continue                    # a key: step 3
                try:
                    label, body = hid.split_pin(pin)
                except ValueError:
                    I.warnings.append(f"{m.ref(rid)}: upstream {pin!r} is neither an H nor a key (namespace:key)")
                    continue
                if label and label not in labels:
                    continue                    # an H of another universe: not ours to resolve
                target = rows.get(T.follow(rows, body))
                if not target or target["anchor"] not in I.ent_of_record:
                    I.warnings.append(f"{m.ref(rid)}: upstream {pin} names no published H of this universe")
                    continue
                uf.union(I.ent_of_record[target["anchor"]], I.ent_of_record[m.ref(rid)], f"upstream {pin}")
    # 3. keys: the records holding one `ns:key` are one entity, in a member or across members
    ent_keys = defaultdict(set)
    for m in live:
        for rid, rec in m.raw.items():
            er = I.ent_of_record.get(m.ref(rid))
            if er:
                props = dict(rec.get("properties") or {})
                props["upstream"] = [*(props.get("upstream") or []), *(rec.get("_upstream") or [])]
                ent_keys[er].update(hkeys.of_record(I.keyconf, props))
    for er, (m, e) in I.ents.items():
        ent_keys[er].update(hkeys.of_record(I.keyconf, {p: v for p, v in e["properties"].items() if p != "upstream"}))
    holders = defaultdict(list)
    for er in sorted(ent_keys):
        for k in ent_keys[er]:
            holders[k].append(er)
    for k, group in sorted(holders.items()):
        a = group[0]
        for b in group[1:]:
            sa, sb = I.ents[a][1]["schema"], I.ents[b][1]["schema"]
            if compatible(sa, sb, I.anc):
                uf.union(a, b, f"key {k}")
            else:
                I.warnings.append(f"key {k} is on a {sa} ({a}) and a {sb} ({b}): kept apart")
    # 4. the same identifier across members
    keyprops = set(hkeys.by_property(I.keyconf))
    seen_ids = defaultdict(list)
    for er, (m, e) in I.ents.items():
        props = m.schemas.get(e["schema"], {}).get("props", {})
        for p, vals in e["properties"].items():
            if p != "upstream" and p not in keyprops and (props.get(p) or {}).get("type") in ID_TYPES:
                for v in vals:
                    seen_ids[(p, htypes.norm_identifier(v))].append(er)
    for (p, v), group in sorted(seen_ids.items()):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if I.ents[a][0] is not I.ents[b][0] and compatible(I.ents[a][1]["schema"], I.ents[b][1]["schema"], I.anc):
                    uf.union(a, b, f"same {p}")
    I.blocked = uf.blocked

    for er in I.ents:
        I.clusters.setdefault(uf.find(er), []).append(er)
    I.cl_records = {c: sorted(r for er in es for r in records_of[er]) for c, es in I.clusters.items()}
    I.keys = {c: sorted(set().union(*(ent_keys.get(er, set()) for er in es))) for c, es in I.clusters.items()}
    cluster_of_record = {r: c for c, rs in I.cl_records.items() for r in rs}

    order = sorted(rows.items(), key=lambda kv: (-T.RANK[kv[1]["state"]], kv[1].get("seq", 0), kv[0]))
    redirected = []
    for body, row in order:
        alive = [r for r in row.get("members") or [] if r in cluster_of_record]
        c = cluster_of_record.get(row["anchor"]) or \
            (Counter(cluster_of_record[r] for r in alive).most_common(1)[0][0] if alive else None)
        if c is None:
            I.hs[body] = {"state": row["state"], "flags": {"orphaned"}, "cluster": None, "row": row}
        elif row.get("redirect"):
            redirected.append((body, row, c))
        elif c in I.claimed:
            I.hs[body] = {"state": row["state"], "flags": {"redirected"}, "cluster": None,
                          "redirect": I.claimed[c], "row": row}
        else:
            I.claimed[c] = body
            I.hs[body] = {"state": row["state"], "flags": set(), "cluster": c, "row": row}
    for body, row, c in redirected:
        target = T.follow(rows, body)
        if I.claimed.get(c) == target:
            I.hs[body] = {"state": row["state"], "flags": {"redirected"}, "cluster": None, "redirect": target, "row": row}
        elif c in I.claimed:
            I.hs[body] = {"state": row["state"], "flags": {"redirected", "stale"}, "cluster": None,
                          "redirect": I.claimed[c], "row": row}
        else:                            # the merge it recorded no longer holds: it is a page again
            I.claimed[c] = body
            I.hs[body] = {"state": row["state"], "flags": {"stale"}, "cluster": c, "row": row}
    for c in sorted(I.clusters):
        if c in I.claimed:
            continue
        anchor = I.cl_records[c][0]
        key = primary_key(I, c)
        seed = f"key|{key}" if key else anchor        # keyed by its primary key: the H holds whatever the records do
        body, n = hid.derive(I.uid, seed), 1
        while body in I.hs or body in rows:
            n += 1
            body = hid.derive(I.uid, f"{seed}#{n}")
        I.claimed[c] = body
        I.hs[body] = {"state": "c", "flags": set(), "cluster": c, "anchor": anchor, **({"key": key} if key else {})}
    I.h_of_entity = {er: I.claimed[c] for c, es in I.clusters.items() for er in es}

    loaded = {m.name for m in live}
    for body, h in I.hs.items():
        c = h["cluster"]
        if c is None:
            continue
        a = (h.get("row") or {}).get("anchor") or h.get("anchor")
        I.anchor_of[c] = a if a in cluster_of_record and cluster_of_record[a] == c else I.cl_records[c][0]
        row = h.get("row")
        if row and row["state"] == "d":
            basis = {r for r in row.get("members") or [] if r.split("/", 1)[0] in loaded}
            if basis != set(I.cl_records[c]):
                h["flags"].add("stale")
        for p in LIFE + ("gender",):
            vals = [v for er in I.clusters[c] for v in I.ents[er][1]["properties"].get(p) or []]
            if (p == "gender" and len(set(vals)) > 1) or (p != "gender" and dates_disagree(vals)):
                h["flags"].add("conflict")
                h.setdefault("disagree", []).append(p)
        for ns in unique_clashes(I, c):
            h["flags"].add("conflict")
            h.setdefault("disagree", []).append(f"key:{ns}")
    return I


def unique_clashes(I: Identity, c) -> list[str]:
    """The `unique` namespaces a cluster holds more than one key of."""
    per = Counter(k.split(":", 1)[0] for k in I.keys.get(c, ()))
    return sorted(ns for ns, n in per.items() if n > 1 and (I.keyconf["namespaces"].get(ns) or {}).get("unique"))


def primary_key(I: Identity, c) -> str | None:
    """The key a cluster is keyed by: of the `primary` namespaces, most preferred first, the first
    it holds exactly one key of (two keys of one namespace say nothing for sure)."""
    for ns in I.keyconf["primary"]:
        held = [k for k in I.keys.get(c, ()) if k.split(":", 1)[0] == ns]
        if len(held) == 1:
            return held[0]
    return None


def canon_rows(I: Identity, titles: dict, schema_of: dict) -> list[dict]:
    out = []
    for body, h in sorted(I.hs.items()):
        flags = hid.flag_value(h["flags"])
        c = h["cluster"]
        row = h.get("row") or {}
        out.append({"h": hid.fmt(body, h["state"], flags), "body": body, "state": h["state"],
                    "flags": hid.flag_names(flags), "anchor": row.get("anchor") or h.get("anchor"),
                    "members": I.cl_records[c] if c else [], "title": titles.get(body) or row.get("title", ""),
                    "schema": schema_of.get(body), "redirect": h.get("redirect"),
                    "disagree": h.get("disagree", []), "keys": I.keys.get(c, []) if c else []})
    return out
