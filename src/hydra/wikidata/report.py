"""report.py — how `hydra-ctl wikidata` prints: plain headings, aligned columns, one next step.

Each printer returns lines. Colour is hydra.cli.style's (plain text when piped); a column is padded
before it is coloured, so colour never shifts one."""
from __future__ import annotations

import re
import textwrap

from hydra.cli import style

KINDS = {"external-id": "id on another site", "wikibase-item": "link to an item", "time": "date",
         "quantity": "number", "url": "web address", "string": "text", "monolingualtext": "text",
         "commonsMedia": "image", "globe-coordinate": "coordinates", "math": "formula"}


def kind(datatype: str) -> str:
    return KINDS.get(datatype, datatype or "?")


def _cut(text, n) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def table(rows, head, widths, styles=()) -> list[str]:
    """Rows of strings -> aligned lines. A negative width right-aligns (numbers)."""
    def cell(text, w, i, header=False):
        text = _cut(text, abs(w))
        text = text.ljust(w) if w > 0 else text.rjust(-w)
        fn = styles[i] if i < len(styles) and not header else ""
        return getattr(style, fn)(text) if fn else text
    out = [style.aside("  " + "  ".join(cell(h, w, i, True) for i, (h, w) in enumerate(zip(head, widths))).rstrip())]
    for r in rows:
        out.append("  " + "  ".join(cell(c, w, i) for i, (c, w) in enumerate(zip(r, widths))).rstrip())
    return out


def heading(text, count=None, aside="") -> list[str]:
    return ["", style.name(text.upper()) + (style.aside(f"  {count}") if count is not None else "")
            + (style.aside("  " + aside) if aside else "")]


def props(found: dict) -> list[str]:
    out = []
    for pid, p in found.items():
        out.append(f"{style.accent(pid)}  {style.name(p['label'] or '(no English label)')}"
                   f"  {style.aside('· ' + kind(p['datatype']))}")
        out += ["    " + line for line in textwrap.wrap(re.split(r"\s*\[|;", p["description"])[0], 84)]
        if p["formatter"]:
            out.append("    " + style.aside("link  ") + p["formatter"].replace("$1", "{id}"))
        out.append("")
    return out[:-1]


def imported(path, n_records, n_items, rep, labels, qids) -> list[str]:
    fields, records = [], []
    for (pid, target), row in rep["mapped"].items():
        line = (target, str(row["count"]), f"{pid} {labels.get(pid, '')}".strip(), "; ".join(row["examples"][:2]))
        (fields if "." in target else records).append(line)
    head, widths, styles = ["Field", "Times", "Wikidata property", "Example"], [26, -5, 34, 42], ["name", "", "accent", "aside"]
    out = [f"{style.verb('Imported')} {style.plural(n_items, 'Wikidata item')} as {style.plural(n_records, 'record')}"
           f"  {style.aside(str(path))}"]
    out += heading("Copied into fields", sum(int(r[1]) for r in fields), "a Wikidata claim became a value in a Hydra field")
    out += table(sorted(fields), head, widths, styles)
    out += heading("Made into records", sum(int(r[1]) for r in records), "a claim between two things became a record of its own")
    out += table(sorted(records), ["Record"] + head[1:], widths, styles)
    if rep["left_out"]:
        out += heading("Left out")
        for why, row in sorted(rep["left_out"].items()):
            ex = "; ".join(row["examples"][:2])
            out.append(f"  {row['count']:>3}  {why}" + (style.aside(f"   e.g. {_cut(ex, 70)}") if ex else ""))
    claims = sum(u["claims"] for u in rep["unread"].values())
    out += ["", f"{style.note(f'{claims:,} claims')} on {len({p for _, p in rep['unread']})} other properties have no rule yet. "
                f"See them: {style.accent('hydra-ctl wikidata unread ' + ' '.join(qids))}"]
    return out


def unread(groups, n_items, claims, limit, show_all) -> list[str]:
    fits, ids, other = groups["fits"], groups["ids"], groups["other"]
    out = [f"{style.verb('Read')} {style.plural(n_items, 'item')}. "
           f"{style.note(f'{claims:,} claims')} on {len(fits) + len(ids) + len(other)} properties have no rule yet."]
    take = lambda rows: rows if show_all else rows[:limit]
    more = lambda rows: [style.aside(f"  … {len(rows) - limit} more (--all)")] if not show_all and len(rows) > limit else []

    # web addresses all land in the same two fields: keep the commonest, fold the rest into one line
    urls = [r for r in fits if r["datatype"] == "url"]
    folded = [] if show_all else urls[1:]
    shown = [r for r in fits if r not in folded]
    rows = []
    for r in take(shown):
        f = r["fields"]
        rows.append((r["pid"], r["label"], str(r["items"]), r["example"], ", ".join(f[:2]) + (f"  +{len(f) - 2}" if len(f) > 2 else "")))
    out += heading("Could fill a field", len(fits), "a property that fits a Hydra field by type and name")
    out += table(rows, ["Code", "Wikidata calls it", "On", "Example", "Could fill"], [7, 28, -3, 26, 40],
                 ["accent", "name", "", "aside", ""]) + more(shown)
    if folded:
        names = ", ".join(re.sub(r"\s*URL$", "", r["label"], flags=re.I) for r in folded[:5])
        out.append(style.aside(f"  + {len(folded)} more web addresses ({names}, …) → website or sourceUrl; they are links, rarely worth a field"))

    out += heading("Ids on other sites", len(ids), "they match the same person across sources (keys.yaml); they are not fields")
    out += table([(r["pid"], r["label"], str(r["items"]), r["example"]) for r in take(ids)],
                 ["Code", "Wikidata calls it", "On", "Example"], [7, 36, -3, 36], ["accent", "name", "", "aside"]) + more(ids)

    out += heading("Nothing fits", len(other), "no Hydra field suggested; many are really relationships or events")
    out += table([(r["pid"], r["label"], str(r["items"]), kind(r["datatype"]), "/".join(sorted(r["schemas"])), r["example"])
                  for r in take(other)],
                 ["Code", "Wikidata calls it", "On", "Kind", "Type", "Example"], [7, 30, -3, 16, 14, 28],
                 ["accent", "name", "", "aside", "aside", "aside"]) + more(other)

    out += ["", style.aside("On = how many of the items carry that claim."),
            "To read one, add a line under its type in .hydra/rules/wikidata.yaml, e.g. " + style.accent("P2048: height")
            + style.aside("   (look a code up: hydra-ctl wikidata prop P2048)")]
    return out
