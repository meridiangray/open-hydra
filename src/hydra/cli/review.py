"""review: the guided session over the last build's open questions.

    hydra-ctl review [<dir>] [--only KIND] [--no-build]

Walks the questions in order (merges, references, placements, stale,
contradictions, verdict issues), one at a time. Every question is the same:
a subject, "Which is better?", and the real alternatives, numbered, each with
one line of evidence; the current choice is marked "now".

    [1/3] Loyal Provisions
    Which is better?
      1  under Meridian Electrotech GmbH   Ownership, parent company   now
      2  under Gideon Fairbank                 Ownership, co-founder and proprietor
      ? not sure   u undo   q quit

A merge question shows the records themselves above the choices: each one's
fields as the record gives them (its claims), one value per line, marked = (the
same values) or ≠ (a conflict) against the record asked about. Tab and
Shift+Tab switch between all fields, fields in both, and conflicting fields.

A number answers; `?` or Enter leaves it open; `u` undoes the last answer of
this session; `q` leaves. In a terminal a key answers at once, no Enter. Each answer is written to
.hydra/review/verdicts.yaml at once (so quitting loses nothing); the
archive is rebuilt once, when you leave. Placements that involve a record you
merged in this session are skipped (their keys change once the merge is
built): the rebuild on exit reports them as still open.

What an answer saves is unchanged: a merge is confirmed or rejected (with its
basis), a reference pinned, a placement confirmed. Picking a different parent
confirms it and clears the old decision; when the old parent came from the
position rules it is rejected instead, so the rule does not put the record
back. The alternatives offered for a placement are the ones `tree` lists under
the record ("also under"), so the two always agree."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from hydra import build, layout, resources, schema
from hydra.cli import style, todo
from hydra.cli.answer import set_verdict
from hydra.review import ids


class Quit(Exception):
    pass


def read_key() -> str:
    """One key press, no Enter: "tab", "shift-tab", "enter", or the character.
    A terminal sends nothing for Shift alone, so the view keys are Tab and Shift+Tab."""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return "shift-tab" if msvcrt.getwch() == "\x0f" else ""
    else:
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = os.read(fd, 1).decode(errors="ignore")
            if ch == "\x1b":                              # Shift+Tab is ESC [ Z
                seq = os.read(fd, 8).decode(errors="ignore") if select.select([fd], [], [], 0.05)[0] else ""
                return "shift-tab" if seq == "[Z" else ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch == "\x03":
        raise KeyboardInterrupt
    return {"\t": "tab", "\r": "enter", "\n": "enter", "\x04": "q"}.get(ch, ch)


MERGE_VIEWS = ("all fields", "fields in both", "conflicting fields")
REFERENCE_VIEWS = ("all fields", "name fields", "matching fields")
NAMES = ("name", "alias", "weakAlias", "previousName")


def merge_kind(clash: set, detail: str = "") -> str:
    """The kind line of a merge question: how many records, and what conflicts."""
    parts = ["Merge"] + ([detail] if detail else []) + ([f"conflicting: {', '.join(sorted(clash))}"] if clash else [])
    return " · ".join(parts)


def opening(clash: set) -> int:
    """The view a two-record question opens on: the conflicting fields when there
    are any (what has to be decided), else all fields."""
    return MERGE_VIEWS.index("conflicting fields") if clash else 0


def fields(view: int, props: dict, other: dict, clash: set) -> list[str]:
    """The fields of `props` a view shows: all, the ones `other` also has, the conflicting ones."""
    return [k for k in props if view == 0 or (view == 1 and k in other) or (view == 2 and k in clash)]


def field_parts(props: dict, keys: list[str], width: int, mark=None, lead=None) -> list[list[tuple[str, str]]]:
    """A record's fields as (text, style) lines, one value per line.
    mark(k, v, first) -> " ", "=" or "≠" after the field name; lead(k, v, first)
    -> the three columns before it ("   ", or " → " for the value asked about)."""
    out = []
    for k in keys:
        for i, v in enumerate(props.get(k) or [""]):
            m = mark(k, v, i == 0) if mark else " "
            out.append([((lead(k, v, i == 0) if lead else "   "), "note"), (f"{k if i == 0 else '':<{width}}", "accent"),
                        (" ", ""), (m, "note" if m == "≠" else "aside"), (" ", ""), (v, "note" if m == "≠" else "")])
    return out


def block(head: list[tuple[str, str]], props: dict, keys: list[str], width: int, ref: dict | None = None,
          clash: set = frozenset()) -> list[str]:
    """A record as field / value lines, one value per line. Against `ref`, a
    field is marked = (the same values) or ≠ (a conflict)."""
    mark = None
    if ref is not None:
        mark = lambda k, v, first: (" " if not first else "≠" if k in clash
                                    else "=" if set(props[k]) == set(ref.get(k) or ()) else " ")
    return [style.styled(head)] + [style.styled([("  ", "")] + p) for p in field_parts(props, keys, width, mark)]


def boxed(label: str, lines: list[list[tuple[str, str]]]) -> list[str]:
    """Lines in a labelled box: the record a question is about, above the
    numbered choices (a reference's "Link from", a merge's "Merge with", a
    placement's "Placing")."""
    plain = lambda p: "".join(t for t, _ in p)
    w = max([len(plain(p)) for p in lines] + [len(label) + 2]) + 2
    out = [style.aside("  ┌─ ") + style.name(label) + style.aside(" " + "─" * (w - len(label) - 3) + "┐")]
    out += [style.aside("  │ ") + style.styled(p) + " " * (w - 2 - len(plain(p))) + style.aside(" │") for p in lines]
    return out + [style.aside("  └" + "─" * w + "┘")]


class Session:
    def __init__(self, root, ask=input, say=print, keys=None):
        self.root, self.ask, self.say = Path(root), ask, say
        self.keys = keys                                  # read_key in a terminal; else answers are lines
        self._records: dict | None = None                # record / entity -> (schema, props), from claims.jsonl
        self.vfile = self.root / layout.VERDICTS
        self.undo: list[list[tuple[str, object]]] = []    # per answer: (key, previous value)
        self.merged: set[str] = set()                     # records merged in this session
        self.done: set[str] = set()                       # row ids answered or covered
        self.writes = 0
        self.skipped_placements = 0
        self._merge_ends: dict[str, tuple] = {}          # merge row id -> its two records
        self._chart = None                                # (nodes, also_under), read once
        self.counter = ""                                 # "[1/3]", shown before the subject

    # ---- writing ---------------------------------------------------------

    def _current(self) -> dict:
        import yaml
        return (yaml.safe_load(self.vfile.read_text(encoding="utf-8")) or {}) if self.vfile.is_file() else {}

    def write(self, changes: list[tuple[str, object]], said: str = "") -> None:
        """Apply several (key, value|None) at once; one undo step."""
        cur = self._current()
        self.undo.append([(k, cur.get(k)) for k, _ in changes])
        for k, v in changes:
            set_verdict(self.vfile, k, v)
        self.say(style.aside("  saved") + (f"   {said}" if said else ""))
        self.writes += 1

    def undo_last(self) -> list[str]:
        if not self.undo:
            self.say(style.aside("  nothing to undo"))
            return []
        step = self.undo.pop()
        for k, prev in step:
            set_verdict(self.vfile, k, prev)
        self.say(style.aside("  undone"))
        return [k for k, _ in step]

    # ---- asking ----------------------------------------------------------

    def _key(self) -> str:
        if self.keys:
            sys.stdout.write("> ")
            sys.stdout.flush()
            got = self.keys()
            self.say(got if len(got) == 1 else "")
            return "" if got == "enter" else got
        got = self.ask("> ") or ""
        return "tab" if got == "\t" else got.strip()

    def choose(self, subject: str, options: list[tuple[str, str, bool]], notes=(), extra=None,
               render=None, views=MERGE_VIEWS, question: str = "Which is better?", view: int = 0,
               kind: str = "") -> str:
        """Show the question; return "1".."N", an `extra` key, "" (not sure) or
        "u". Raises Quit. options: (label, evidence, is the current choice).
        `render(view)` -> the lines shown above the choices, one of `views`
        (several: Tab / Shift+Tab change the view and show the question again);
        `view` is the one shown first; `kind` says what sort of question it is,
        on the line above the subject."""
        while True:
            if kind:
                self.say(style.aside(self.counter + " ") + style.accent(kind))
                self.say("  " + style.name(subject))
            else:
                self.say(style.aside(self.counter + " ") + style.name(subject))
            for line in notes:
                self.say(line)
            if render:
                for line in render(view):
                    self.say(line)
                if len(views) > 1:
                    self.say("  " + "   ".join(style.name(f"[{v}]") if i == view else style.aside(v)
                                               for i, v in enumerate(views)) + style.aside("      Tab / Shift+Tab"))
            self.say(question)
            width = max([len(label) for label, _, _ in options] + [0])
            for n, (label, detail, now) in enumerate(options, 1):
                self.say(f"  {style.name(str(n))}  {label:<{width}}   " + style.aside(detail)
                         + (("   " + style.note("now")) if now else ""))
            for k, label in (extra or {}).items():
                self.say(f"  {style.name(k)}  {label}")
            self.say(style.aside("  ? not sure   u undo   q quit"))
            keys = {str(n) for n in range(1, len(options) + 1)} | set(extra or {})
            while True:
                got = self._key()
                if got in ("tab", "shift-tab") and render and len(views) > 1:
                    view = (view + (1 if got == "tab" else -1)) % len(views)
                    break
                if got in ("", "?"):
                    return ""
                if got == "q":
                    raise Quit
                if got == "u" or got in keys:
                    return got
                self.say(style.aside(f"  pick a number from 1 to {len(options)}, ? not sure, u undo or q quit"))

    def _claims(self) -> dict:
        """{"record": {id: (schema, props)}, "entity": {...}} from claims.jsonl, read once."""
        if self._records is None:
            self._records = {"record": {}, "entity": {}}
            p = self.root / layout.CLAIMS_JSONL
            for line in p.read_text(encoding="utf-8").splitlines() if p.is_file() else ():
                if line.strip():
                    c = json.loads(line)
                    for by in ("record", "entity"):
                        _, props = self._records[by].setdefault(c[by], (c.get("schema", ""), {}))
                        if c["value"] not in props.setdefault(c["prop"], []):
                            props[c["prop"]].append(c["value"])
        return self._records

    def record(self, rid: str) -> tuple[str, dict]:
        """(schema, props) as the record itself gives them: its claims, by `record`."""
        return self._claims()["record"].get(rid) or ("", {})

    def entity(self, eid: str) -> tuple[str, dict]:
        """(schema, props) of an entity after merging: every record's values."""
        return self._claims()["entity"].get(eid) or ("", {})

    # ---- the walk --------------------------------------------------------

    def run(self, only: str = "") -> None:
        open_ = todo.collect(self.root)
        queue = self._questions(open_, only)
        i = 0
        while i < len(queue):
            kind, item = queue[i]
            if self._covered(kind, item):
                i += 1
                continue
            self.counter = f"\n[{i + 1}/{len(queue)}]"
            got = getattr(self, f"_ask_{kind}")(item, queue)
            if got == "undo":
                keys = self.undo_last()
                for k in keys:
                    self.done.discard(k)
                    self.merged.difference_update(self._merge_ends.pop(k, ()))
                if keys:
                    i = max(0, i - 1)
                continue
            i += 1

    def _questions(self, open_: dict, only: str) -> list[tuple[str, object]]:
        out = []
        kinds = [k for k in todo.KINDS if not only or k == only]
        for kind in kinds:
            rows = open_[kind]
            if kind == "merges":
                groups: dict[str, list[dict]] = {}
                for r in rows:
                    if r.get("group"):
                        groups.setdefault(r["group"], []).append(r)
                    else:
                        out.append(("merge", [r]))
                out += [("merge", g) for g in groups.values()]
            else:
                out += [({"references": "reference", "placements": "placement", "stale": "stale",
                          "contradictions": "contradiction", "verdicts": "verdict"}[kind], r) for r in rows]
        return out

    def _covered(self, kind: str, item) -> bool:
        rows = item if isinstance(item, list) else [item]
        if all(r["id"] in self.done for r in rows):
            return True
        if kind == "placement" and ({item.get("sub"), item.get("sup")} & self.merged):
            self.skipped_placements += 1
            self.done.add(item["id"])
            return True
        return False

    # ---- merges: a single pair, or a group (alternatives of one question) ----

    def _look(self, rid: str) -> tuple[str, dict]:
        """A record's own fields, or the entity's when no record has that id."""
        got = self.record(rid)
        return got if got[1] else self.entity(rid)

    def _pair(self, a: str, b: str, clash: set, decision=None):
        """render(view) for two records, b marked against a; `decision`: a
        (text, style) line shown above them (a stale or contradicted decision)."""
        (sa, pa), (sb, pb) = self._look(a), self._look(b)
        width = max(map(len, [*pa, *pb, "name"]))
        head = lambda rid, s: [("  ", ""), (rid, "name"), ("   ", ""), (s, "aside")]
        top = [""] + ([style.styled(decision)] if decision else [])
        return lambda view: (top + [""] * bool(decision) + block(head(a, sa), pa, fields(view, pa, pb, clash), width)
                             + [""] + block(head(b, sb), pb, fields(view, pb, pa, clash), width, pa, clash) + [""])

    def _ask_merge(self, rows: list[dict], queue) -> str:
        clash_of = lambda r: {c["prop"] for c in r.get("conflicts") or []}
        recs = {x: self.record(x) for r in rows for x in (r["a"], r["b"])}
        width = max(map(len, [k for _, p in recs.values() for k in p] + ["name"]))
        head = lambda rid, n="": [("  ", ""), (f"{n}  " if n else "", "name"), (rid, "name"),
                                  ("   ", ""), (recs[rid][0], "aside")]
        if len(rows) == 1:
            r = rows[0]
            got = self.choose(f"{r.get('acap')}   and   {r.get('bcap')}",
                              [("one entity", "", False), ("two entities", "", False)],
                              render=self._pair(r["a"], r["b"], clash_of(r)), view=opening(clash_of(r)),
                              kind=merge_kind(clash_of(r)))
            if got == "u":
                return "undo"
            if got:
                st = "confirmed" if got == "1" else "rejected"
                self.write([(r["id"], {"status": st, "basis": r.get("basis")} if r.get("basis") else st)],
                           "one entity" if st == "confirmed" else "two entities")
                self.done.add(r["id"])
                if st == "confirmed":
                    self.merged |= {r["a"], r["b"]}
                    self._merge_ends[r["id"]] = (r["a"], r["b"])
            return got
        ends = [{r["a"], r["b"]} for r in rows]
        focus = set.intersection(*ends)
        fid = sorted(focus)[0] if focus else None
        fcap = next((r["acap"] if r["a"] == fid else r["bcap"] for r in rows), fid) if fid else None
        opts = []
        for r in rows:
            other, oid = (r["bcap"], r["b"]) if r["a"] == fid else (r["acap"], r["a"])
            opts.append((f"the same as {other}", oid, False) if fid
                        else (f"{r['acap']} and {r['bcap']} are one", f"{r['a']}  {r['b']}", False))
        opts.append(("none of these", "", False))

        def render(view: int) -> list[str]:
            if not fid:                                   # no shared record: each option is a pair
                out = []
                for n, r in enumerate(rows, 1):
                    (_, pa), (_, pb), cl = recs[r["a"]], recs[r["b"]], clash_of(r)
                    out += ([""] + block(head(r["a"], str(n)), pa, fields(view, pa, pb, cl), width)
                            + [""] + block([("     ", "")] + head(r["b"])[1:], pb, fields(view, pb, pa, cl),
                                           width, pa, cl))
                return out + [""]
            pf = recs[fid][1]
            union = {k for x, (_, p) in recs.items() if x != fid for k in p}
            every = set().union(*(clash_of(r) for r in rows))
            subject = [[(fid, "name"), ("   ", ""), (recs[fid][0], "aside")]] + field_parts(
                pf, fields(view, pf, union, every), width)
            out = [""] + boxed("Merge with", subject)      # the record the numbered ones would join
            for n, r in enumerate(rows, 1):
                po = recs[r["b"] if r["a"] == fid else r["a"]][1]
                out += [""] + block(head(r["b"] if r["a"] == fid else r["a"], str(n)), po,
                                    fields(view, po, pf, clash_of(r)), width, pf, clash_of(r))
            return out + [""]

        every = set().union(*(clash_of(r) for r in rows))
        got = self.choose(fcap if fid else "these records", opts, render=render, view=opening(every),
                          kind=merge_kind(every, f"{len(rows)} candidates" if fid else f"{len(rows)} pairs"))
        if got == "u":
            return "undo"
        if got:
            changes = []
            for n, r in enumerate(rows, 1):
                st = "confirmed" if got == str(n) else "rejected"
                changes.append((r["id"], {"status": st, "basis": r.get("basis")} if r.get("basis") else st))
                self.done.add(r["id"])
                if st == "confirmed":
                    self.merged |= {r["a"], r["b"]}
                    self._merge_ends[r["id"]] = (r["a"], r["b"])
            self.write(changes, opts[int(got) - 1][0])
        return got

    # ---- references ----------------------------------------------------------

    def _ask_reference(self, r: dict, queue) -> str:
        from hydra.identity import types
        cands = r.get("candidates") or []
        rec, prop, value = r.get("record") or "", r.get("prop") or "", str(r.get("value") or "")
        rs, rp = self._look(rec)
        ents = [self.entity(c["id"]) for c in cands]
        key = types.norm_text(value)
        same = lambda v: types.norm_text(v) == key
        width = max(map(len, [*rp] + [k for _, p in ents for k in p] + ["name"]))

        def render(view: int) -> list[str]:
            shown = lambda p: [k for k in p if view == 0 or (view == 1 and k in NAMES)
                               or (view == 2 and any(same(v) for v in p[k]))]
            top = [[(rec, "name"), ("   ", ""), (rs or r.get("schema") or "", "aside")]] + field_parts(
                rp, list(rp), max(map(len, [*rp, "name"])),
                lead=lambda k, v, first: " → " if k == prop and v == value else "   ")
            out = [""] + boxed("Link from", top)
            for n, (c, (s, p)) in enumerate(zip(cands, ents), 1):
                head = [("  ", ""), (f"{n}  ", "name"), (c["id"], "name"), ("   ", ""), (s or c.get("schema") or "", "aside")]
                out += [""] + [style.styled(head)] + [
                    style.styled([("  ", "")] + x)
                    for x in field_parts(p, shown(p), width, mark=lambda k, v, first: "=" if same(v) else " ")]
            return out + [""]

        opts = [(str(c.get("caption") or c.get("id")), str(c.get("id") or ""), False) for c in cands]
        opts.append(("neither" if len(cands) == 2 else "none of these", "", False))
        got = self.choose(f"{rec}   {r.get('group')}   {value}", opts, render=render,
                          views=REFERENCE_VIEWS, question=f"Which record is \"{value}\"?",
                          kind=f"Reference · a name with {len(cands)} possible records")
        if got == "u":
            return "undo"
        if got:
            pick = int(got)
            self.write([(r["id"], "none" if pick > len(cands) else cands[pick - 1]["id"])], opts[pick - 1][0])
            self.done.add(r["id"])
        return got

    # ---- placements ----------------------------------------------------------

    def _chart_data(self):
        """The declared read's nodes and every record's other parents, as `tree` shows them."""
        if self._chart is None:
            from hydra import tree
            from hydra.review import verdicts as vd
            from hydra.structure import fold
            p = self.root / layout.READS["declared"]
            ir = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"nodes": {}}
            schema.load(root=self.root)
            fam = self.root / layout.DIRECTION
            direction = fold.load_direction(fam if fam.is_file() else None)
            self._chart = (ir.get("nodes") or {}, tree.also_under(ir, direction, vd.load(self.root)[0]),
                           direction)
        return self._chart

    def _ask_placement(self, r: dict, queue) -> str:
        crit = r.get("criteria") or ""
        by_rule = crit.startswith("rules:")
        rid, cur = r["sub"], r["sup"]
        nodes, also, _ = self._chart_data()
        cap = lambda i: (nodes.get(i) or {}).get("caption") or i
        rels = (nodes.get(rid) or {}).get("rels") or []
        through = lambda at, via=None: next((x["record"] for x in rels if x.get("at") == at and x.get("record")
                                             and (via is None or x.get("via") == via)), None)
        parents = [(cur, None if by_rule else through(cur))]
        for x in also.get(rid, []):
            if x["why"] in ("cycle", "rejected") or x["at"] in {p for p, _ in parents}:
                continue                                  # a loop, or one you already turned down
            parents.append((x["at"], through(x["at"], x["via"])))
        opts = [(f"under {cap(p)}", p, p == cur) for p, _ in parents]
        rs, rp = self.entity(rid)
        shown = {rec: self.record(rec) for _, rec in parents if rec}
        width = max(map(len, [*rp] + [k for _, p in shown.values() for k in p] + ["name"]))

        def render(view: int) -> list[str]:
            subject = [[(rid, "name"), ("   ", ""), (rs, "aside")]] + field_parts(rp, list(rp), width)
            out = [""] + boxed("Placing", subject)          # the record the numbered parents would hold
            for n, (p, rec) in enumerate(parents, 1):
                now = [("   ", ""), ("now", "note")] if p == cur else []
                if rec:
                    s, props = shown[rec]
                    out += [""] + block([("  ", ""), (f"{n}  ", "name"), (rec, "name"), ("   ", ""), (s, "aside")]
                                        + now, props, list(props), width)
                else:                                     # placed by the position rules, not one record
                    out += ["", style.styled([("  ", ""), (f"{n}  ", "name"), (p, "name"), ("   ", ""),
                                              (crit, "aside")] + now)]
            return out + [""]

        same = [x for _, x in queue if isinstance(x, dict) and x.get("rel") == "placedUnder"
                and x.get("criteria") == crit and x["id"] not in self.done] if by_rule else []
        extra = {"a": f"keep all {len(same)} placed by {crit}"} if len(same) > 1 else None
        got = self.choose(cap(rid), opts, extra=extra, render=render, views=("all fields",),
                          kind="Placement · " + (crit or "which parent the tree draws"))
        if got == "u":
            return "undo"
        if got == "a":
            self.write([(x["id"], "confirmed") for x in same], f"kept {len(same)} placed by {crit}")
            self.done |= {x["id"] for x in same}
        elif got:
            pick = parents[int(got) - 1][0]
            if pick == cur:
                changes = [(r["id"], "confirmed")]
            else:                                         # the new parent pinned; the old one let go
                changes = [(ids.place_key(rid, pick), "confirmed"), (r["id"], "rejected" if by_rule else None)]
            self.write(changes, f"{cap(rid)} under {cap(pick)}")
            self.done.add(r["id"])
        return got

    # ---- stale decisions, contradictions, decision problems ------------------------

    def _ask_stale(self, r: dict, queue) -> str:
        if r.get("status") == "confirmed-stale":
            clash = {c["prop"] for c in r.get("conflicts") or []}
            decision = [("  decision   ", "aside"), (r["id"], "name"), ("   one entity   ", ""),
                        ("evidence changed", "note")]
            got = self.choose(f"{r.get('acap')}   and   {r.get('bcap')}",
                              [("one entity", "", True), ("two entities", "", False),
                               ("forget the decision", "", False)],
                              render=self._pair(r["a"], r["b"], clash, decision), view=opening(clash),
                              kind="Stale decision · the evidence changed since you decided")
            if got == "u":
                return "undo"
            if got == "1":
                self.write([(r["id"], {"status": "confirmed", "basis": r.get("basis")})], "one entity")
            elif got == "2":
                self.write([(r["id"], {"status": "rejected", "basis": r.get("basis")})], "two entities")
            elif got == "3":
                self.write([(r["id"], None)], "forgotten")
        else:
            got = self.choose(r["id"], [("forget the decision", "", False), ("keep it", "", True)],
                              kind="Stale decision · it matches nothing now",
                              notes=[style.styled([("  decision   ", "aside"), (r["id"], "name"),
                                                   (f"   {r.get('status')}   ", ""), ("matches nothing", "note")])])
            if got == "u":
                return "undo"
            if got == "1":
                self.write([(r["id"], None)], "forgotten")
        if got:
            self.done.add(r["id"])
        return got

    def _ask_contradiction(self, r: dict, queue) -> str:
        clash = {c["prop"] for c in r.get("conflicts") or []}
        decision = [("  decision   ", "aside"), (str(r.get("of") or ""), "name"), ("   two entities   ", ""),
                    ("merged anyway", "note")]
        got = self.choose(f"{r.get('a')}   and   {r.get('b')}",
                          [("one entity", "", False), ("two entities", "", True)],
                          render=self._pair(r["a"], r["b"], clash, decision), view=opening(clash),
                          kind="Contradiction · you said two entities, but they were merged")
        if got == "u":
            return "undo"
        if got == "1":
            self.write([(r["of"], None)], "one entity")
        if got:
            self.done.add(r["id"])
        return got

    def _ask_verdict(self, r: dict, queue) -> str:
        removable = r["id"] in self._current()
        opts = ([("remove that decision", "", False)] if removable else []) + [("keep it", "", True)]
        got = self.choose(str(r.get("message") or r["id"]), opts, kind="Decision problem")
        if got == "u":
            return "undo"
        if got == "1" and removable:
            self.write([(r["id"], None)], "removed")
        if got:
            self.done.add(r["id"])
        return got


def _table(header: list[str], rows: list[list]) -> list[str]:
    """Rows under a dim header: the first column left, numbers right."""
    cells = [header] + [[str(x) for x in r] for r in rows]
    w = [max(len(c[i]) for c in cells) for i in range(len(header))]
    line = lambda c: "  " + f"{c[0]:<{w[0]}}" + "".join(f"   {x:>{w[i + 1]}}" for i, x in enumerate(c[1:]))
    return [style.aside(line(cells[0]).rstrip())] + [line(c).rstrip() for c in cells[1:]]


def counts(root) -> dict[str, int]:
    return {k: len(v) for k, v in todo.collect(root).items()}


def main(argv: list[str] | None = None, ask=input, say=print) -> int:
    ap = argparse.ArgumentParser(prog="hydra-ctl review", description="The guided review session.")
    ap.add_argument("dir", nargs="?", help="the archive (default: the active one, or this folder)")
    ap.add_argument("--only", choices=todo.KINDS, default="")
    ap.add_argument("--no-build", action="store_true", help="do not rebuild when leaving")
    a = ap.parse_args(argv)
    root = resources.ensure_built(resources.archive(a.dir))
    before = counts(root)
    s = Session(root, ask, say, keys=read_key if ask is input and sys.stdin.isatty() and sys.stdout.isatty() else None)
    kinds = [k for k, n in before.items() if n and (not a.only or k == a.only)]
    asked = {}                                    # a group of merges is one question
    for kind, _ in s._questions(todo.collect(root), a.only):
        asked[kind] = asked.get(kind, 0) + 1
    single = {"merges": "merge", "references": "reference", "placements": "placement", "stale": "stale",
              "contradictions": "contradiction", "verdicts": "verdict"}
    name = (resources.yamlcache.load(root / layout.MANIFEST) or {}).get("name") or root.name
    say(style.name("review") + "   " + name)
    say("")
    rows = [[k, before[k], asked.get(single[k], 0)] for k in kinds]
    rows.append(["total", sum(r[1] for r in rows), sum(r[2] for r in rows)])
    for line in _table(["kind", "rows", "questions"], rows):
        say(line)
    try:
        s.run(a.only)
    except (Quit, EOFError, KeyboardInterrupt):
        pass
    say("")
    done = [("answered", s.writes)] + ([("skipped placements", s.skipped_placements)]   # a record they hold
                                       if s.skipped_placements else [])                 # was merged here
    w = max(len(k) for k, _ in done)
    for k, n in done:
        say(style.aside(f"  {k:<{w}}") + f"   {n}")
    if s.writes and not a.no_build:
        summary = build.build_archive(root)
        after = counts(root)
        shown = [k for k in after if before[k] or after[k]]
        new = any(after[k] > before[k] for k in shown)
        header = ["kind", "before", "now"] + (["new"] if new else [])
        rows = [[k, before[k], after[k]] + ([max(after[k] - before[k], 0) or ""] if new else []) for k in shown]
        say("")
        for line in _table(header, rows):
            say(line)
        say("")
        say(build.report(root, summary, verb="Rebuilt"))
    return 0
