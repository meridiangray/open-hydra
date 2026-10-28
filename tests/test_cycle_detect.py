"""cycles.detect() against SYNTHETIC corpora with real loops (the demo has
none — 88 one-hop edges, zero instance cycles), plus the read integration:
a cut edge stays a real placement but is never a primary-parent candidate."""

import yaml


import test_fold as t  # noqa: E402
from hydra import schema  # noqa: E402
from hydra.identity import merge as m  # noqa: E402
from hydra.shape import reads, rules  # noqa: E402
from hydra.structure import cycles, fold  # noqa: E402

GENERIC = t.TEMPLATE / ".hydra" / "rules" / "defaults" / "positions.yaml"


def rec(id_, sch, **props):
    return {"id": id_, "schema": sch, "_collection": "syn",
            "properties": {k: v if isinstance(v, list) else [v] for k, v in props.items()}}


def _run(records):
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    names = sorted(schema.SCHEMA)
    mm = m.merge(records, names, params_dir=t.PARAMS)
    ff = fold.fold(records, mm, names, direction=fam, params_dir=t.PARAMS)
    schema_of = {r["id"]: r["schema"] for r in records}
    cm = cycles.cycle_map(names, fam)
    return ff, schema_of, cm, fam


def _ir(records):
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    g = yaml.safe_load(GENERIC.read_text(encoding="utf-8")) or {}
    return reads.build_reads(records, rules.compile_rules(g, None, direction=fam),
                             direction=fam, params_dir=t.PARAMS)


def _ring():
    """Org One -> Org Two -> Org Three -> Org One via Membership: a 3-cycle
    of DISTINCT entities, no short loop inside it."""
    orgs = [rec(f"o{i}", "Organization", name=n) for i, n in enumerate(["Org One", "Org Two", "Org Three"], 1)]
    ms = [rec(f"m{i}", "Membership", member=a, organization=b)
          for i, (a, b) in enumerate([("Org One", "Org Two"), ("Org Two", "Org Three"),
                                      ("Org Three", "Org One")], 1)]
    return orgs + ms


def _contract_loop(same=True):
    return [rec("ca", "Company", name="Acme Corp"),
            rec("cb", "Company", name="Acme Corp" if same else "Beta Corp"),
            rec("k1", "Contract", name="Contract K1", authority="Acme Corp"),
            rec("aw", "ContractAward", contract="Contract K1",
                supplier="Acme Corp" if same else "Beta Corp")]


def test_long_ring_is_found_by_tarjan_with_no_pivot():
    ff, so, cm, _ = _run(_ring())
    d = cycles.detect(ff["placements"], so, cm)
    assert len(d["cycles"]) == 1 and sorted(d["cycles"][0]["members"]) == ["o1", "o2", "o3"]
    assert d["pivots"] == []                       # no short loop inside it
    assert len(d["cycles"][0]["cut"]) == 1         # one cut makes a 3-ring acyclic


def test_pivot_check_finds_company_contract_company_when_same_entity():
    recs = _contract_loop(same=True)
    ff, so, cm, _ = _run(recs)
    d = cycles.detect(ff["placements"], so, cm)
    assert any(p["pivot"] == "k1" and p["other"] == "ca" for p in d["pivots"])
    assert len(d["cycles"]) == 1


def test_same_class_different_entities_is_not_a_cycle():
    ff, so, cm, _ = _run(_contract_loop(same=False))
    d = cycles.detect(ff["placements"], so, cm)
    assert d["pivots"] == [] and d["cycles"] == []


def test_edges_are_tagged_with_tier_form_and_cycle_id():
    ff, so, cm, _ = _run(_ring())
    d = cycles.detect(ff["placements"], so, cm)
    es = [e for e in d["edges"] if e["label"] == "Membership"]
    assert es and all(e["tier"] == "direct" and e["form"] == "combined" for e in es)
    assert len({e["cycle"] for e in es}) == 1 and es[0]["cycle"].startswith("cyc-")


def test_cut_choice_prefers_the_ended_edge_and_is_deterministic():
    recs = _ring()
    next(r for r in recs if r["id"] == "m2")["properties"]["endDate"] = ["2001-01-01"]
    ff, so, cm, _ = _run(recs)
    d1 = cycles.detect(ff["placements"], so, cm)
    d2 = cycles.detect(ff["placements"], so, cm)
    assert d1["cycles"] == d2["cycles"]
    assert d1["cycles"][0]["cut"][0]["child"] == "o2"      # m2: Org Two -> Org Three, ended


def test_acyclic_demo_corpus_reports_no_cycles():
    t._load()
    ir = _ir(t._load_demo_records())
    assert ir["report"]["cycles"]["cycles"] == [] and ir["report"]["cycles"]["pivots"] == []


def test_cut_edge_is_excluded_from_primary_parent_but_kept_as_a_placement():
    recs = _ring()
    ir = _ir(recs)
    cut = ir["report"]["cycles"]["cut"]
    assert len(cut) == 1
    child, container, label = cut[0]
    n = ir["nodes"]
    assert n[child]["pid"] != container                 # never the primary parent
    for rid in ("o1", "o2", "o3"):                      # tree still has no cycle
        seen, cur = {rid}, n[rid]["pid"]
        while cur:
            assert cur not in seen
            seen.add(cur)
            cur = n[cur]["pid"]


def test_relations_sidecar_is_in_compile_rules_and_yaml_safe():
    t._load()
    fam = fold.load_direction(t.DIRECTION)
    r = rules.compile_rules({}, None, direction=fam)
    rel = r["relations"]["families"]
    assert rel["Directorship"]["form"] == "combined" and rel["Vehicle.owner"]["form"] == "dag"
    assert rel["Family"]["form"] == "ag"
    assert yaml.safe_load(yaml.safe_dump(r["relations"])) == r["relations"]
    assert rules.compile_rules({}, None)["relations"] == {}      # no direction -> empty, not guessed


def test_parallel_edges_in_one_direction_do_not_all_get_cut():
    """Alpha->Beta twice (Membership + Ownership) and Beta->Alpha once: one
    cut breaks the loop, so exactly one edge is cut and it is a real one."""
    recs = [rec("a", "Company", name="Alpha Co"), rec("b", "Company", name="Beta Co"),
            rec("o1", "Ownership", owner="Alpha Co", asset="Beta Co"),
            rec("o2", "Ownership", owner="Beta Co", asset="Alpha Co"),
            rec("m1", "Membership", member="Alpha Co", organization="Beta Co")]
    ff, so, cm, _fam = _run(recs)
    d = cycles.detect(ff["placements"], so, cm)
    assert len(d["cut"]) == 1
    assert len(d["cycles"][0]["cut"]) == 1


# ---- primary parent: a legal-entity container beats a project ------------


def _parent_of(ir, caption):
    nid = next(i for i, n in ir["nodes"].items() if n["caption"] == caption)
    return ir["nodes"][ir["nodes"][nid]["pid"]]["caption"] if ir["nodes"][nid].get("pid") else None


def _org_vs_project(**org_edge):
    return [rec("w", "Person", name="Wally Person"),
            rec("o", "Organization", name="Big Org"),
            rec("pr", "Project", name="Side Project"),
            rec("m1", "Membership", member="Wally Person", organization="Big Org",
                **{"startDate": "2001-01-01", **org_edge}),
            rec("pp", "ProjectParticipant", project="Side Project", participant="Wally Person",
                startDate="2010-01-01")]


def test_org_beats_a_more_recent_project():
    assert _parent_of(_ir(_org_vs_project()), "Wally Person") == "Big Org"


def test_ended_org_membership_still_beats_an_active_project():
    """Wallace Wright: Leader of Hawthorne (ended 2010) outranks the projects he
    is still on; the node carries its `former` flag, nothing is dropped."""
    assert _parent_of(_ir(_org_vs_project(endDate="2005-01-01")), "Wally Person") == "Big Org"


def test_cut_org_edge_falls_back_to_the_project_not_a_loop():
    """Big Org is itself a member of Wally Co, which is a member of Big Org: a
    PublicBody/Company/Organization loop. Whatever is cut, nobody ends up
    their own ancestor in the single tree."""
    recs = _org_vs_project() + [
        rec("c", "Company", name="Wally Co"), rec("pb", "PublicBody", name="Wally Board"),
        rec("m2", "Membership", member="Big Org", organization="Wally Co"),
        rec("m3", "Membership", member="Wally Co", organization="Wally Board"),
        rec("m4", "Membership", member="Wally Board", organization="Big Org")]
    ir = _ir(recs)
    for start in ir["nodes"]:
        seen, cur = set(), start
        while cur and cur in ir["nodes"]:
            assert cur not in seen, "cycle in primary-parent chain"
            seen.add(cur)
            cur = ir["nodes"][cur].get("pid")
    assert ir["report"]["cycles"]["cut"]
