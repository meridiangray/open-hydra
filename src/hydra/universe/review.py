"""review.py — the only writers of the H-table, besides publishing.

    merge A B     the two are one: a decided row holding both; the younger row redirects
    reject A B    never one: both rows decided, each naming the other in `not`
    publish Hs    something outside now points at them: computed -> published
    caption H t   a universe caption pin (an archive's own pin still wins on display)

A and B are Hs as the last universe build shows them (`H-c0-...`, `H-...` or a
bare body), or record refs (`self/case:a1`). Every command reads
`universe/.parsed/canon.jsonl`, so the universe is built first; the next build
shows the effect.
"""
from __future__ import annotations

from hydra.universe import hid, layer, table


def _built(root) -> dict:
    return {r["body"]: r for r in layer.read_parsed(root, "canon.jsonl")}


def resolve(built: dict, ref: str) -> str:
    """An H, a bare body or a record ref -> the body of the live H holding it."""
    if hid.is_h(ref):
        body = hid.body(ref)
        if body not in built:
            raise SystemExit(f"hydra: no H {ref} in the last universe build")
    else:
        if "/" not in ref:
            ref = f"{layer.SELF}/{ref}"
        body = next((b for b, r in built.items() if ref in r["members"]), None)
        if body is None:
            raise SystemExit(f"hydra: no record {ref} in the last universe build")
    seen = set()
    while built[body].get("redirect") and body not in seen:
        seen.add(body)
        body = built[body]["redirect"]
    return body


def merge(root, a: str, b: str, *, by: str = "", source: str = "") -> str:
    built, rows = _built(root), table.load(root)
    ba, bb = resolve(built, a), resolve(built, b)
    if ba == bb:
        return ba
    # the one that keeps its H: decided before published before computed, then older
    rank = lambda x: (-table.RANK[built[x]["state"]], rows.get(x, {}).get("seq", 1 << 30), x)
    keep, gone = sorted((ba, bb), key=rank)
    members = sorted(set(built[keep]["members"]) | set(built[gone]["members"]))
    row = table.promote(rows, keep, "d", anchor=built[keep]["anchor"], members=members,
                        title=built[keep].get("title", ""), by=by, source=source)
    row["not"] = [x for x in row.get("not") or [] if x != gone]
    if gone in rows:                     # a promised H is never dropped: it now points at the survivor
        rows[gone]["redirect"] = keep
        rows[gone]["not"] = [x for x in rows[gone].get("not") or [] if x != keep]
    table.save(root, rows)
    return keep


def reject(root, a: str, b: str, *, by: str = "", source: str = "") -> tuple[str, str]:
    built, rows = _built(root), table.load(root)
    ba, bb = resolve(built, a), resolve(built, b)
    if ba == bb:
        raise SystemExit(f"hydra: {a} and {b} are one H (H-{ba}); split it with `universe split`")
    for x, y in ((ba, bb), (bb, ba)):
        row = table.promote(rows, x, "d", anchor=built[x]["anchor"], members=built[x]["members"],
                            title=built[x].get("title", ""), by=by, source=source)
        row["not"] = sorted(set(row.get("not") or []) | {y})
    table.save(root, rows)
    return ba, bb


def split(root, h: str, records: list[str], *, by: str = "") -> tuple[str, str]:
    """Take `records` (refs) out of H `h` into an H of their own; the two are never one again."""
    built, rows = _built(root), table.load(root)
    body = resolve(built, h)
    refs = [r if "/" in r else f"{layer.SELF}/{r}" for r in records]
    have = set(built[body]["members"])
    if not refs or not set(refs) <= have or set(refs) == have:
        raise SystemExit(f"hydra: give some (not all) of H-{body}'s records: {', '.join(sorted(have))}")
    rest = sorted(have - set(refs))
    anchor = built[body]["anchor"] if built[body]["anchor"] in rest else rest[0]
    keep = table.promote(rows, body, "d", anchor=anchor, members=rest, title=built[body].get("title", ""), by=by)
    new_anchor = sorted(refs)[0]
    uid = layer.read_manifest(root)["uid"]
    new, n = hid.derive(str(uid), new_anchor), 1
    while new in rows or new in built:
        n += 1
        new = hid.derive(str(uid), f"{new_anchor}#{n}")
    other = table.promote(rows, new, "d", anchor=new_anchor, members=sorted(refs), by=by)
    keep["not"] = sorted(set(keep.get("not") or []) | {new})
    other["not"] = sorted(set(other.get("not") or []) | {body})
    table.save(root, rows)
    return body, new


def publish(root, bodies, *, by: str = "") -> int:
    built, rows = _built(root), table.load(root)
    n = 0
    for b in bodies:
        r = built.get(b)
        if r and not r.get("redirect") and r["members"] and r["state"] == "c":
            table.promote(rows, b, "p", anchor=r["anchor"], members=r["members"], title=r.get("title", ""), by=by)
            n += 1
    if n:
        table.save(root, rows)
    return n


def publish_pinned(root, records, *, by: str = "") -> int:
    """An `upstream` H pin is a promise the H holds: a computed H a record pins becomes published,
    so the pin takes (the build resolves pins only to Hs in the table). Keys are not Hs: skipped.
    -> how many were published; 0 when there is no universe build yet."""
    from pathlib import Path
    from hydra import layout
    if not (Path(root) / layout.UNIVERSE_PARSED / "canon.jsonl").is_file():
        return 0
    bodies = set()
    for r in records:
        pins = (r.get("properties") or {}).get("upstream") or []
        for v in pins if isinstance(pins, list) else [pins]:
            try:
                bodies.add(hid.split_pin(v)[1])
            except ValueError:
                pass
    return publish(root, sorted(bodies), by=by) if bodies else 0


def caption(root, h: str, text: str | None) -> str:
    body = resolve(_built(root), h)
    layer.set_pin(root, f"cap-{body}", text)
    return body
