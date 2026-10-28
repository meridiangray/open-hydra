"""Rule compilation: generic + hierarchy -> positions, edges, guide; and the
hint-rule matcher that .hydra/rules/hints.yaml uses (`match:`/`set:`)."""
from __future__ import annotations
import heapq
from functools import lru_cache
import re
from hydra import layout, schema
from hydra.identity.types import norm_text


# rules: generic + declared -> parsed
def _positions_of(doc) -> dict:
    doc = doc or {}
    if "positions" in doc:
        return dict(doc.get("positions") or {})
    return {k: v for k, v in doc.items()
            if k not in ("hints", "carry", "model", "subject")}


POSITION_KEYS = ("below", "above", "titles", "outside")   # all a position in positions.yaml takes


def _as_list(v) -> list:
    return [str(x) for x in (v if isinstance(v, list) else [v] if v else [])]


def model_from_direction(direction=None) -> dict:
    """The compiler `model` dict, from direction.yaml (replaces the old
    engine's relations.default_model(): same keys, one flat source)."""
    f = direction or {}
    return {
        "above_props": list(dict.fromkeys(f.get("above") or [])),
        "lateral": list(dict.fromkeys(list(f.get("lateral") or []) + ["Similar", "Placement"])),
        "dual": list(f.get("dual") or []),
        "governing": list(f.get("governing") or []),
        "edge_positions": dict(f.get("edge_positions") or {}),
        "exclude": list(f.get("exclude") or []),
    }


def compile_rules(generic=None, declared=None, observed=(), direction=None) -> dict:
    """generic ∪ declared ∪ titles seen in the corpus -> {positions, edges:
    [[lower, upper]], observed, unrelated, issues, carry}. A position in both keeps
    the generic titles and adds the declared ones; its below/above are the
    declared ones when the declared entry gives any, else the generic ones (so
    adding a title to a default position never moves it). This dict IS parsed.yaml."""
    generic, declared = generic or {}, declared or {}
    issues, pos = [], {}
    for src, doc in (("generic", generic), ("declared", declared)):
        for name, d in _positions_of(doc).items():
            if d is not None and not isinstance(d, dict):
                issues.append(f"{src}: position '{name}' must be a mapping")
                continue
            d = d or {}
            cur = pos.setdefault(str(name), {"below": [], "above": [], "titles": [],
                                             "outside": False, "source": src})
            for k in d:
                if k not in POSITION_KEYS:
                    issues.append(f"{src}: position '{name}': '{k}' is not read (a position takes "
                                  f"{', '.join(POSITION_KEYS)}; display goes in .hydra/rules/hints.yaml)")
            if src == "declared":
                if cur["source"] == "generic":
                    cur["source"] = "generic+declared"
                if "below" in d or "above" in d:           # declared relations replace the generic ones
                    cur["below"], cur["above"] = [], []
            for k in ("below", "above", "titles"):
                for v in _as_list(d.get(k)):
                    if v not in cur[k]:
                        cur[k].append(v)
            if "outside" in d:
                cur["outside"] = bool(d["outside"])
    for name, d in list(pos.items()):                      # implied positions
        for ref in d["below"] + d["above"]:
            if ref not in pos:
                pos[ref] = {"below": [], "above": [], "titles": [], "outside": False, "source": "implied"}
                issues.append(f"'{name}' refers to '{ref}', which is not defined")
    edges = []
    for name, d in pos.items():
        for up in d["below"]:
            if [name, up] not in edges:
                edges.append([name, up])
        for lo in d["above"]:
            if [lo, name] not in edges:
                edges.append([lo, name])
    edges, cut = _acyclic(edges)
    issues += [f"cycle broken at {lo} below {up}" for lo, up in cut]
    for name, d in pos.items():
        d["uppers"] = sorted({u for lo, u in edges if lo == name})
    obs = {t: canonical(t, pos) for t in observed}
    related = {n for e in edges for n in e}
    unrelated = sorted({c or t for t, c in obs.items()
                        if (c or t) not in related and not (pos.get(c or "") or {}).get("outside")})
    for src, doc in (("generic", generic), ("declared", declared)):
        if doc.get("hints"):
            issues.append(f"{src}: `hints:` belongs in .hydra/rules/hints.yaml; ignored here")
    carry = list(dict.fromkeys(_as_list(generic.get("carry")) + _as_list(declared.get("carry"))))
    model = model_from_direction(direction)
    for src, doc in (("generic", generic), ("declared", declared)):
        if doc.get("model"):
            issues.append(f"{src}: `model:` is no longer read; relationship policy lives in {layout.DIRECTION}")
    relations_block = {}
    if direction:
        from hydra.structure import (
            cycles,
        )  # local: cycles -> fold -> merge, none import rules
        relations_block = cycles.sidecar(
            cycles.cycle_map(sorted(schema.SCHEMA), direction), direction)
    return {"positions": pos, "edges": edges, "observed": obs, "unrelated": unrelated,
            "relations": relations_block,
            "issues": issues, "carry": carry, "model": model,
            "guide": build_guide(model)}


def build_guide(model=None) -> dict:
    """Derived agent attach-guide, emitted into parsed.yaml: which record
    forms compile into hierarchy (strongest first), each vertical edge/prop's
    reverse name (the agent-writeable direction), and where titles come from.
    Generated from schema.SCHEMA x model — never authored, can't drift."""
    model = model or model_from_direction()
    above = set(model["above_props"])
    vertical, propforms = [], []
    for name in sorted(schema.SCHEMA):
        t = schema.SCHEMA[name] or {}
        pdefs = schema.resolve(name)["props"]
        e = t.get("edge")
        if e:
            sp, tp = e["source"], e["target"]
            if sp in above or tp in above:
                upper = tp if tp in above else sp
                lower = sp if tp in above else tp
                revs = [f"{pd['range']}.{pd['revname']}"
                        for p in (sp, tp)
                        if (pd := pdefs.get(p) or {}).get("range")
                        and pd.get("revname")]
                vertical.append({"schema": name, "lower": lower, "upper": upper,
                                 "role_prop": "role" in pdefs, "reverse": revs})
        else:
            for p, pd in pdefs.items():
                if p in above and pd.get("type") == "entity":
                    rn = pd.get("revname")
                    propforms.append({"schema": name, "prop": p,
                                      "range": pd.get("range"),
                                      "reverse": f"{pd['range']}.{rn}" if rn else None})
    return {
        "ladder": [
            {"conf": "fold",
             "write": ["Occupancy {holder: <person-id>, post: <position-id>}",
                       "Position {name: \"<title>\", organization: <org-id>}"],
             "note": "strongest — holder->post->org folds to person under org with "
                     "the post name as title; post must reach an org "
                     "(Position.organization / Organization.positions) or the "
                     "holder stays a root"},
            {"conf": "edge",
             "write": ["Membership {member: <person-id>, organization: <org-id>, "
                       "role: \"<title>\"}"],
             "note": "relation record — a person->org edge routes through a "
                     "post named by role: (model.edge_positions supplies a "
                     "default when role: is absent) and folds like an "
                     "explicit Position"},
            {"conf": "prop",
             "write": ["Person {position: [\"<title>\"]} + any org membership"],
             "note": "weakest — title only, no relation record; person still "
                     "needs org containment or they stay a root"}],
        "vertical_edges": vertical,
        "prop_forms": propforms,
        "titles": {"sources": ["relation role:", "Person.position:", "Position.name:"],
                   "match": "position names + titles: lists; unruled titles land "
                            "in unrelated:"},
        "feedback": {"folded": "holder->post->org chains that attached",
                     "unresolved": "refs that did not resolve — fix ids/captions",
                     "unrelated": "observed titles with no matching position",
                     "issues": "cycle cuts, implied positions, lint problems"}}


def _acyclic(edges):
    """Drop edges that close a cycle (first-declared wins); returns (kept, cut)."""
    kept, cut = [], []
    for lo, up in edges:
        seen, stack = set(), [up]
        loop = False
        while stack:
            n = stack.pop()
            if n == lo:
                loop = True
                break
            if n not in seen:
                seen.add(n)
                stack += [u for l, u in kept if l == n]
        (cut if loop else kept).append([lo, up])
    return kept, cut


def closure(edges) -> tuple[dict, dict]:
    """Transitive reach of the position graph -> (above, below):
    above[p] = every position p sits under, below[p] = every one under p."""
    ups, downs = {}, {}
    for lo, up in edges:
        ups.setdefault(lo, set()).add(up)
        downs.setdefault(up, set()).add(lo)
    def reach(adj):
        out = {}
        for n in adj:
            seen, st = set(), list(adj[n])
            while st:
                m = st.pop()
                if m not in seen:
                    seen.add(m)
                    st += adj.get(m, ())
            out[n] = seen
        return out
    return reach(ups), reach(downs)


def rank_order(ids, pos_of, edges, tie) -> list:
    """Order ids so whoever holds a position above another's comes first — a
    linear extension of the position graph, unrelated ids by `tie`. Purely
    relational: no depth or level is ever computed."""
    above, below = closure(edges)
    ids = sorted(ids, key=tie)
    at = {i: pos_of(i) for i in ids}
    by_pos = {}
    for i in ids:
        by_pos.setdefault(at[i], []).append(i)
    wait = {i: sum(len(by_pos.get(p, ())) for p in above.get(at[i], ())) for i in ids}
    idx = {i: k for k, i in enumerate(ids)}
    heap = [idx[i] for i in ids if not wait[i]]
    heapq.heapify(heap)
    out = []
    while heap:
        i = ids[heapq.heappop(heap)]
        out.append(i)
        for q in below.get(at[i], ()) if at[i] is not None else ():
            for j in by_pos.get(q, ()):
                wait[j] -= 1
                if not wait[j]:
                    heapq.heappush(heap, idx[j])
    return out


def canonical(title: str, positions: dict) -> str | None:
    """A title's position: exact name or `titles` match, ignoring case, accents
    and punctuation (`types.norm_text`, the same normalizer matching uses). No parsing — anything else is just its own title."""
    t = norm_text(title)
    if not t:
        return None
    for name, d in positions.items():
        if norm_text(name) == t or t in {norm_text(s) for s in d.get("titles") or []}:
            return name
    return None


def rules_mermaid(rules: dict, label: str = "") -> str:
    """Mermaid `graph TD` of the COMPILED position graph (parsed.yaml) — up on
    top, `upper --> lower` edges, provenance colours. Renders on GitHub,
    mermaid.live, or vendored in the view. Unruled titles/issues = comments."""
    pos = rules.get("positions") or {}
    edges = rules.get("edges") or []
    related = {n for e in edges for n in e}
    ids = {n: f"P{i}" for i, n in enumerate(sorted(pos))}
    cls = {"generic": "generic", "declared": "declared",
           "generic+declared": "both", "implied": "implied"}

    def node(n):
        d = pos[n]
        sub = []
        if d.get("titles"):
            sub.append(str(len(d["titles"])) + " title" + ("s" if len(d["titles"]) != 1 else ""))
        c = ("outside" if d.get("outside") or n not in related
             else cls.get(d.get("source") or "", "implied"))
        loft = _mesc(n) + (f"<br/>{_mesc(' · '.join(sub))}" if sub else "")   # the break itself unescaped
        return f'    {ids[n]}["{loft}"]:::{c}'

    order = rank_order(pos, lambda n: None if pos[n].get("outside") else n, edges,
                       lambda n: (bool(pos[n].get("outside")), n.lower()))
    out = ["graph TD"]
    if label:
        out.append(f"    %% position graph — {_mesc(label)} (GENERATED)")
    out += ["    classDef generic fill:#dbeafe,stroke:#9ca3af,color:#111827",
            "    classDef declared fill:#dcfce7,stroke:#9ca3af,color:#111827",
            "    classDef both fill:#fef3c7,stroke:#9ca3af,color:#111827",
            "    classDef implied fill:#f3f4f6,stroke:#9ca3af,color:#111827",
            "    classDef outside fill:#ffffff,stroke:#d1d5db,stroke-dasharray:4 3,color:#111827"]
    out += [f"    {ids[u]} --> {ids[l]}" for l, u in edges if l in ids and u in ids]
    out += [node(n) for n in order]
    side = [n for n in order if pos[n].get("outside") or n not in related]
    if side:
        out.append("    %% outside / no relations: " + ", ".join(side))
    if rules.get("unrelated"):
        out.append("    %% observed titles with no rule: " + ", ".join(rules["unrelated"]))
    for i in rules.get("issues") or []:
        out.append(f"    %% ISSUE: {_mesc(i)}")
    return "\n".join(out) + "\n"


def _mesc(s) -> str:
    """Mermaid label escape: quotes/brackets out of [\"...\"] node labels."""
    return (str(s).replace('"', "'").replace("[", "(").replace("]", ")")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# hints
def match_to_when(match) -> dict | None:
    """The flat `match:` form -> the `when:` condition tree `hint_match` reads.
    Every key must hold. `schema` is an is-a test, `position` the node's
    position, `linked_by` a linked-evidence schema, `titled` a title the
    record's own data states (`stated_titles`), `any:` a list of matches;
    any other key is a property (or `a|b` for several): a plain value means
    equals, a list means equals any, `{contains: rx}` a regular expression,
    `{exists: true}` has a value. `titled` takes a value, a list or `{contains: rx}`."""
    if not isinstance(match, dict) or not match:
        return None
    out = []
    for k, v in match.items():
        if k == "schema":
            out.append({"schema_is": v})
        elif k == "position":
            out.append({"position_is": v})
        elif k == "linked_by":
            out.append({"linked_by": v})
        elif k == "titled":
            if isinstance(v, dict) and "contains" in v:
                out.append({"titled_contains": str(v["contains"])})
            elif isinstance(v, list):
                out.append({"any": [{"titled_equals": str(x)} for x in v]})
            elif isinstance(v, (str, int, float)):
                out.append({"titled_equals": str(v)})
            else:
                return None
        elif k == "any":
            subs = [match_to_when(m) for m in v] if isinstance(v, list) else [None]
            if None in subs:
                return None
            out.append({"any": subs})
        elif isinstance(v, dict):
            if "contains" in v:
                out.append({"prop": k, "contains": str(v["contains"])})
            elif v.get("exists"):
                out.append({"any": [{"has_prop": x.strip()} for x in k.split("|")]})
            else:
                return None
        elif isinstance(v, list):
            out.append({"any": [{"prop": k, "equals": str(x)} for x in v]})
        else:
            out.append({"prop": k, "equals": str(v)})
    return {"all": out}


def rule_when(h) -> dict | None:
    """A hint rule's condition, from its `match:`."""
    return match_to_when(h["match"]) if isinstance(h, dict) and "match" in h else None


IMAGES = ("thumb", "portrait", "logo")      # a rule's image effects; a node collects each as a list
EFFECTS = ("position", "badge") + IMAGES


def rule_set(h) -> dict:
    """A hint rule's effects, from its `set:`."""
    base = h.get("set") if isinstance(h, dict) and isinstance(h.get("set"), dict) else {}
    return {k: base[k] for k in EFFECTS if base.get(k)}


def inside_resources(path: str) -> bool:
    """A rule's image path stays inside .hydra/resources/ (a link, or a relative
    path with no `..`); anything else is never handed to a view."""
    from pathlib import PurePosixPath, PureWindowsPath
    p = str(path)
    if "://" in p:
        return True
    pp = PurePosixPath(p.replace("\\", "/"))
    return bool(p) and not pp.is_absolute() and not PureWindowsPath(p).drive and ".." not in pp.parts


def uses_titled(when) -> bool:
    """True when a condition tree tests `titled` anywhere."""
    if not isinstance(when, dict):
        return False
    return "titled_equals" in when or "titled_contains" in when or \
        any(uses_titled(w) for k in ("all", "any") for w in when.get(k) or [])


@lru_cache(maxsize=None)
def _regex(pattern: str):
    try:
        return re.compile(pattern, re.I)
    except re.error:
        return None


def _search(rx, value: str) -> bool:
    """A `contains:` pattern against a value as written, or with case, accents
    and punctuation set aside (`norm_text`), so `sentinel` finds "SENTINÉL"."""
    return bool(rx.search(value) or rx.search(norm_text(value)))


def bad_patterns(when) -> list[str]:
    """Every `contains:` pattern in a condition tree that is not a valid
    regular expression."""
    if not isinstance(when, dict):
        return []
    pats = [str(when[k]) for k in ("contains", "titled_contains") if k in when]
    out = [p for p in pats if _regex(p) is None]
    for k in ("all", "any"):
        for w in when.get(k) or []:
            out += bad_patterns(w)
    return out


def hint_match(when: dict, props: dict, schema_name: str, linked=(), position=None,
               titles=(), why: list | None = None) -> bool:
    """Whether a condition tree holds for a node. `titles` are the node's
    stated titles ([field, value], `stated_titles`); `why`, when given,
    collects the [field, value] pairs that made it hold (only from branches
    that held)."""
    if not isinstance(when, dict):
        return False
    if "all" in when:
        got: list = []
        ok = all(hint_match(w, props, schema_name, linked, position, titles, got) for w in when["all"])
        if ok and why is not None:
            why += got
        return ok
    if "any" in when:
        for w in when["any"]:
            got = []
            if hint_match(w, props, schema_name, linked, position, titles, got):
                if why is not None:
                    why += got
                return True
        return False
    hit: list = []
    if "position_is" in when:
        if position and norm_text(position) == norm_text(when["position_is"]):
            hit = [["position", position]]
    elif "schema_is" in when:
        if schema.is_a(schema_name, when["schema_is"]):
            hit = [["schema", schema_name]]
    elif "has_prop" in when:
        hit = [[when["has_prop"], v] for v in (props.get(when["has_prop"]) or [])[:1]]
    elif "linked_by" in when:
        hit = [["linked_by", when["linked_by"]]] if any(
            x.get("schema") == when["linked_by"] if isinstance(x, dict) else x == when["linked_by"]
            for x in (linked or ())) else []
    elif "titled_equals" in when:
        hit = [list(t) for t in titles or () if norm_text(t[1]) == norm_text(when["titled_equals"])]
    elif "titled_contains" in when:
        rx = _regex(when["titled_contains"])
        hit = [list(t) for t in titles or () if rx and _search(rx, t[1])]
    elif "prop" in when:
        vals = [(p.strip(), v) for p in str(when["prop"]).split("|") for v in props.get(p.strip()) or []]
        if "contains" in when:
            rx = _regex(when["contains"])
            hit = [[p, v] for p, v in vals if rx and _search(rx, v)]
        elif "equals" in when:
            hit = [[p, v] for p, v in vals if norm_text(v) == norm_text(when["equals"])]
    if hit and why is not None:
        why += hit
    return bool(hit)


def eval_hints(props: dict, schema_name: str, hints: list, linked=(), position=None) -> list:
    out = []
    for h in hints or []:
        b = rule_set(h).get("badge")
        if b and b not in out and hint_match(rule_when(h), props, schema_name, linked, position):
            out.append(b)
    return out
