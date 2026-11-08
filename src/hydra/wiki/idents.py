"""idents.py — the keys an entry is known by elsewhere, in its infobox.

The universe build puts each page's keys (`upstream` keys, and properties keys.yaml maps to a
namespace) on the page, primary first. This shows them as one "Identifiers" row: the
namespace's label, the key, linked when the namespace has a `url`. Every key also reaches
the page as /k/<namespace>/<key> and through search.
"""
from __future__ import annotations

import html

from hydra.wiki import views

e = html.escape


def infobox_rows(p, c: views.Ctx) -> list[tuple[str, str]]:
    ks = p.get("keys") or []
    if not ks:
        return []
    from hydra import keys as hkeys
    conf = c.wiki.keyconf
    out = []
    for k in ks:
        key = f"<a href='{e(k['url'])}' rel=nofollow>{e(k['key'])}</a>" if k.get("url") else e(k["key"])
        prop = (conf["namespaces"].get(k["ns"]) or {}).get("property")      # a key read from a property keeps its footnotes
        cites = sorted({n for v in (c.values(p, prop) if prop else ())
                        if hkeys.norm(conf, k["ns"], str(v.get("value") or "")) == k["key"] for n in v["cites"]})
        out.append(f"<span class=meta>{e(k['label'])}</span> {key}{c.sup(cites)}")
    return [("Identifiers", "<br>".join(out))]


views.INFOBOX_EXTRA.append(infobox_rows)
