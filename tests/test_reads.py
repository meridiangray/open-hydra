"""reads.py (shape tree + read emission) against the real demo corpus.
Structural invariants of the IR, plus the named acceptance bar that a bare,
ambiguous "Walter White" never lands Walter White Jr. under a container."""

import yaml


import test_fold as t  # noqa: E402
from hydra.shape import reads, rules  # noqa: E402
from hydra.structure import fold  # noqa: E402

GENERIC = t.TEMPLATE / ".hydra" / "rules" / "defaults" / "positions.yaml"
HIERARCHY = t.DEMO.parent / ".hydra" / "rules" / "positions.yaml"


def _ir(declared: bool = False, **kw):
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    g = yaml.safe_load(GENERIC.read_text(encoding="utf-8")) or {}
    d = yaml.safe_load(HIERARCHY.read_text(encoding="utf-8")) if declared else None
    ru = rules.compile_rules(g, d, direction=fam)
    return reads.build_reads(t._load_demo_records(), ru, read="declared" if declared else "generic",
                             direction=fam, params_dir=t.PARAMS, **kw)


def test_ir_has_the_contract_keys():
    ir = _ir()
    assert {"read", "roots", "nodes", "report", "prop_types", "ledger", "rules"} <= set(ir)
    n = next(iter(ir["nodes"].values()))
    assert {"id", "schema", "caption", "position", "tier", "kids", "pid", "alt",
            "placement", "lateral", "rels", "linked", "badges"} <= set(n)


def test_tree_is_consistent_every_node_placed_exactly_once():
    ir = _ir()
    nodes = ir["nodes"]
    for rid, n in nodes.items():
        if n["pid"]:
            assert rid in nodes[n["pid"]]["kids"]
    kid_total = sum(len(n["kids"]) for n in nodes.values())
    assert kid_total + len(ir["roots"]) == len(nodes)
    assert len(set(ir["roots"])) == len(ir["roots"])


def test_no_cycles_in_primary_parent_chain():
    ir = _ir()
    for rid in ir["nodes"]:
        seen, cur = {rid}, ir["nodes"][rid]["pid"]
        while cur:
            assert cur not in seen
            seen.add(cur)
            cur = ir["nodes"][cur]["pid"]


def test_walter_white_jr_is_never_placed_by_the_ambiguous_bare_name():
    ir = _ir()
    jr = next(n for n in ir["nodes"].values() if n["caption"] == "Walter White Jr.")
    assert jr["pid"] is None
    ambiguous = ir["report"]["fold"]["ambiguous_endpoints"]
    assert any(set(a["candidates"]) >= {"p-walt", "p-waltjr"} for a in ambiguous)


def test_walter_keeps_every_container_as_alternates():
    ir = _ir()
    w = next(n for n in ir["nodes"].values() if n["caption"] == "Walter Hartwell White")
    assert "org-heisenberg" in w["alt"] + [w["pid"]]
    assert {"leader", "cook", "planner"} <= set(w["positions"])


def test_declared_read_differs_only_through_rules_and_deterministic():
    a, b = _ir(), _ir(declared=True)
    assert set(a["nodes"]) == set(b["nodes"])
    assert _ir()["roots"] == a["roots"] and _ir(True)["roots"] == b["roots"]
    reads.diff_reads(a, b)


def test_ledger_has_placement_and_sameas_rows():
    ir = _ir()
    rels = {r["rel"] for r in ir["ledger"]}
    assert {"sameAs", "placedUnder"} <= rels


def test_walter_is_placed_under_heisenberg_as_leader_not_under_a_project():
    """Legal-entity containers outrank projects; between his two ended
    memberships the higher role (Leader over cook) wins over recency."""
    ir = _ir()
    n = ir["nodes"]["p-walt"]
    assert n["pid"] == "org-heisenberg" and n["position"] == "Leader"


def test_hints_overrides_match_by_condition_not_by_id():
    ir = _ir(overrides={"hints": [
        {"match": {"schema": "Person", "name|alias": "Walter Hartwell White"}, "set": {"badge": "star"}},
        {"match": {"name": "Nobody At All"}, "set": {"badge": "x"}},
        {"match": {"schema": "Person"}},
        {"when": {"schema_is": "PublicBody"}, "thumb": "icons/pb.svg"},    # not a rule: only match:/set:
    ], "p-walt": {"badge": "old"}})
    hit = [n for n in ir["nodes"].values() if n["badge"] == "star"]
    assert hit and all("Walter Hartwell White" in n["props"]["name"] for n in hit)
    misses = ir["report"]["override_misses"]
    assert "hints[1]" in misses
    assert any(m.startswith("hints[2]") for m in misses)
    assert any(m.startswith("p-walt") for m in misses)
    assert not any(n["badge"] == "old" for n in ir["nodes"].values())


def test_icons_come_from_hints_by_position_not_from_the_position_file():
    ir = _ir(declared=True, overrides={"hints": [
        {"match": {"position": "Leader"}, "set": {"badge": "crown"}}]})
    leaders = [n for n in ir["nodes"].values() if n["position"] == "Leader"]
    assert leaders and all(n["badge"] == "crown" and n["badges"][0] == "crown" for n in leaders)
    assert not ir["report"]["override_misses"]
    g = yaml.safe_load(GENERIC.read_text(encoding="utf-8"))
    assert not any("icon" in d or "thumb" in d for d in g["positions"].values())


def test_match_forms_translate_to_conditions():
    w = rules.match_to_when({"schema": "Person", "name": ["A", "B"], "notes": {"contains": "x"},
                             "birthDate": {"exists": True}, "position": "Leader"})
    assert w["all"][0] == {"schema_is": "Person"}
    assert {"position_is": "Leader"} in w["all"]
    assert rules.match_to_when({"x": {"bogus": 1}}) is None and rules.match_to_when({}) is None


def test_hint_rules_in_a_position_file_are_ignored_and_reported():
    t._load()
    ru = rules.compile_rules({"positions": {"Boss": {}},
                              "hints": [{"match": {"schema": "Person"}, "set": {"badge": "x"}}]})
    assert any("hints.yaml" in i for i in ru["issues"]) and "hints" not in ru


def test_model_overrides_in_a_position_file_are_ignored_and_reported():
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    ru = rules.compile_rules({"positions": {"Boss": {}}, "model": {"exclude": ["Vehicle"]}}, direction=fam)
    assert any("direction.yaml" in i for i in ru["issues"])
    assert ru["model"]["exclude"] == rules.model_from_direction(fam)["exclude"]


def test_accented_and_cyrillic_titles_match_their_positions():
    t._load()
    pos = rules.compile_rules({"positions": {"Président": {"titles": ["Директор"]}}})["positions"]
    assert rules.canonical("president", pos) == "Président"
    assert rules.canonical("ДИРЕКТОР", pos) == "Président"
    assert rules.canonical("Président-directeur", pos) is None


def test_two_children_with_the_same_caption_keep_separate_placement_rows():
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    recs = [{"id": "o1", "schema": "Organization", "properties": {"name": ["Acme Widgets"]}},
            {"id": "p1", "schema": "Person", "properties": {"name": ["John Smith"], "birthDate": ["1970"],
                                                            "alias": ["Senior Smith"]}},
            {"id": "p2", "schema": "Person", "properties": {"name": ["John Smith"], "birthDate": ["1980"],
                                                            "alias": ["Junior Smith"]}},
            {"id": "m1", "schema": "Membership", "properties": {"member": ["Senior Smith"], "organization": ["Acme Widgets"]}},
            {"id": "m2", "schema": "Membership", "properties": {"member": ["Junior Smith"], "organization": ["Acme Widgets"]}}]
    for r in recs:
        r["_collection"] = "c"
    ru = rules.compile_rules(direction=fam)
    ir = reads.build_reads(recs, ru, direction=fam, params_dir=t.PARAMS)
    rows = [e for e in ir["ledger"] if e["rel"] == "placedUnder"]
    assert {(e["sub"], e["sup"]) for e in rows} == {("p1", "o1"), ("p2", "o1")}
    assert {e["subcap"] for e in rows} == {"John Smith"} and len({e["id"] for e in rows}) == 2


def test_a_hint_with_a_bad_regular_expression_is_skipped_and_reported():
    ir = _ir(overrides={"hints": [{"match": {"notes": {"contains": "(unclosed"}}, "set": {"badge": "x"}},
                                  {"match": {"schema": "Person"}, "set": {"badge": "y"}}]})
    misses = ir["report"]["override_misses"]
    assert any(m.startswith("hints[0]") and "regular expression" in m for m in misses)
    assert any(n["badge"] == "y" for n in ir["nodes"].values())


def test_adding_titles_to_a_default_position_keeps_it_where_it_was():
    from hydra.shape import rules
    generic = {"positions": {"Leader": {}, "Member": {"below": ["Leader"], "titles": ["member"]}}}
    titles_only = rules.compile_rules(generic, {"Member": {"titles": ["staffer"]}})
    assert titles_only["positions"]["Member"]["titles"] == ["member", "staffer"]
    assert ["Member", "Leader"] in titles_only["edges"]                       # still below Leader
    moved = rules.compile_rules(generic, {"Member": {"below": [], "titles": ["staffer"]}})
    assert ["Member", "Leader"] not in moved["edges"]                          # an explicit below replaces it


def test_each_shipped_recipe_compiles_clean_and_none_is_on_by_default(tmp_path):
    import yaml
    from hydra import cli, lint, resources
    from hydra.shape import rules
    found = resources.recipes()
    assert set(found) == {"company", "agency", "criminal-organization"}
    generic = yaml.safe_load((resources.TEMPLATE / ".hydra/rules/defaults/positions.yaml").read_text(encoding="utf-8"))
    for name, path in found.items():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        base = None if name == "criminal-organization" else generic       # that one needs the generic positions off
        assert not rules.compile_rules(base, doc)["issues"], name
        assert not [x for x in lint._positions(base, doc) if x["level"] in ("error", "warning")], name
    cli.main(["init", str(tmp_path / "a"), "--prefix", "a"])
    shipped = yaml.safe_load((tmp_path / "a/.hydra/rules/positions.yaml").read_text(encoding="utf-8"))
    assert not shipped and not (tmp_path / "a/recipes").exists()      # comments only; recipes stay in hydra
