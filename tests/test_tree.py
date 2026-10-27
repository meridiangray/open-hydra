"""tree.py: the position tree and the record tree of a built archive."""
import json
import re


import test_fold as t  # noqa: E402
from _template import copy_template  # noqa: E402
from hydra import build, layout, tree  # noqa: E402
from hydra.cli import positions  # noqa: E402


def _built(tmp_path):
    root = copy_template(tmp_path / "a")
    for f in t.DEMO.glob("*.json"):
        (root / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    (root / layout.POSITIONS).write_text((t.DEMO.parent / ".hydra" / "rules" / "positions.yaml").read_text(encoding="utf-8"),
                                         encoding="utf-8")
    build.build_archive(root, now="x")
    return root


def test_position_and_record_trees(tmp_path, capsys):
    root = _built(tmp_path)
    assert positions.main([str(root), "--tree", "--nodes"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Associate   outside") and "└── Special agent" in out
    assert re.search(r"records +.*\n(.*\n)*.* Walter Hartwell White +Person", out)
    assert re.search(r"Enforcer\n.*titles +", out) and " ^" in out
    assert tree.main([str(root), "--ascii"]) == 0
    out = capsys.readouterr().out
    assert "Heisenberg Organization (Organization)\n|-- Walter Hartwell White (Person) — Leader" in out
    assert tree.main([str(root), "--read", "generic", "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) == {"tree"} and doc["tree"]
    assert positions.main([str(root), "--format", "mermaid"]) == 0
    mer = capsys.readouterr().out
    assert mer.startswith("graph TD")
    assert "<br/>" in mer and "&lt;br/&gt;" not in mer             # a line break in a label, not its text


def test_an_unbuilt_archive_says_so(tmp_path):
    import pytest
    root = copy_template(tmp_path / "b")
    with pytest.raises(SystemExit, match="no records to build from yet"):
        tree.main([str(root)])


def test_a_type_or_a_search_picks_where_the_record_tree_starts(tmp_path, capsys):
    from hydra import schema
    root = _built(tmp_path)
    ir, _ = tree._load(root, "declared")
    nodes = ir["nodes"]
    schema.load(root=root)
    starts = tree.starts_of(ir, ["Organization"])
    assert starts and all(schema.is_a(nodes[s]["schema"], "Organization") for s in starts)
    for s in starts:                                       # none sits below another organization
        up = nodes[s].get("pid")
        while up:
            assert not schema.is_a(nodes[up]["schema"], "Organization")
            up = nodes[up].get("pid")
    capsys.readouterr()
    assert tree.main([str(root), "ORGANIZATION", "--format", "json"]) == 0          # any capitalisation
    assert len(json.loads(capsys.readouterr().out)["tree"]) == len(starts)
    assert tree.starts_of(ir, [], "heisen")[0] in {"heisenberg:p-walt", "dea:p-heisenberg-dea"}   # a name's start
    assert tree.main([str(root), "zzqq"]) == 0 and "no record matches" in capsys.readouterr().out


def _accounting(root):
    """(every parent the build's placement step found per record, what the tree shows per record)."""
    from hydra import schema
    from hydra.review import verdicts as vd
    from hydra.structure import fold
    cap = {}
    build.build_archive(root, now="x", capture=cap)
    ir, _ = tree._load(root, "declared")
    nodes = ir["nodes"]
    schema.load(root=root)
    also = tree.also_under(ir, fold.load_direction(root / layout.DIRECTION), vd.load(root)[0])
    found = {c: {p["container"] for p in ps if p["container"] in nodes and p["container"] != c}
             for c, ps in cap["resolved"].f["placements"].items() if c in nodes}
    shown = {c: {nodes[c].get("pid")} | {x["at"] for x in also.get(c, [])} for c in found}
    return found, shown, nodes


def test_the_tree_accounts_for_every_parent_the_build_found(tmp_path):
    root = _built(tmp_path)
    found, shown, nodes = _accounting(root)
    missing = {nodes[c]["caption"]: sorted(nodes[x]["caption"] for x in found[c] - shown[c])
               for c in found if found[c] - shown[c]}
    assert not missing, f"parents the tree does not show: {missing}"
    assert any(len(f) > 1 for f in found.values())          # the demo has records with several parents


def test_every_left_out_parent_says_why(tmp_path):
    """Synthetic: one record with parents in two separate periods, one with a parent
    you rejected, and two organizations that are members of each other (a loop)."""
    from hydra import schema
    from hydra.review import ids
    from hydra.structure import fold
    root = copy_template(tmp_path / "w")
    P = lambda i, n: {"id": i, "schema": "Person", "properties": {"name": [n]}}
    O = lambda i, n, s="Company": {"id": i, "schema": s, "properties": {"name": [n]}}
    E = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: [v] for k, v in p.items()}}
    rows = [P("p1", "Ann Lee"), P("p2", "Bob Ray"), P("p3", "Cy Moe"), O("a", "Alpha Ltd"), O("b", "Beta Ltd"),
            O("o1", "One Group", "Organization"), O("o2", "Two Group", "Organization"),
            E("w1", "Ownership", owner="p1", asset="a", startDate="2000", endDate="2005"),
            E("w2", "Ownership", owner="p2", asset="a", startDate="2010", endDate="2015"),
            E("w3", "Ownership", owner="p1", asset="b"), E("w4", "Ownership", owner="p3", asset="b"),
            E("m1", "Membership", member="o1", organization="o2"), E("m2", "Membership", member="o2", organization="o1")]
    (root / layout.COLLECTIONS_DIR / "w.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    build.build_archive(root, now="x")
    ir, _ = tree._load(root, "declared")
    nodes = ir["nodes"]
    first = nodes["w:b"]["pid"]                                    # reject b's drawn owner; rebuild
    (root / layout.VERDICTS).write_text(f"{ids.place_key('w:b', first)}: rejected\n", encoding="utf-8")
    found, shown, nodes = _accounting(root)
    assert all(found[c] <= shown[c] for c in found)                # nothing the build found is left out
    ir, _ = tree._load(root, "declared")
    schema.load(root=root)
    also = tree.also_under(ir, fold.load_direction(root / layout.DIRECTION), {ids.place_key('w:b', first): "rejected"})
    why = {(c, x["at"]): x["why"] for c, xs in also.items() for x in xs}
    assert why[("w:b", first)] == "rejected"
    assert "earlier" in {why.get(("w:a", p)) for p in ("w:p1", "w:p2")}
    assert "cycle" in {why.get(("w:o1", "w:o2")), why.get(("w:o2", "w:o1"))}
    out = tree.render(tree.record_tree(ir, None, also))
    whys = {line.split()[-1] for line in out.splitlines() if line.strip(" │├└─").startswith("also  ")}
    assert {"rejected", "earlier", "cycle"} <= whys


def test_every_relationship_chart_is_acyclic_and_draws_each_record_once(tmp_path):
    from hydra.review import verdicts as vd
    from hydra.structure import fold
    root = _built(tmp_path)
    ir, _ = tree._load(root, "declared")
    fam = fold.load_direction(root / layout.DIRECTION)
    for kind in tree.PREFER:
        v = tree.prefer(ir, kind, fam, vd.load(root)[0], tree._family_roles(root))
        for c, n in v["nodes"].items():                   # no loops
            seen, up = {c}, n.get("pid")
            while up:
                assert up not in seen, (kind, c)
                seen.add(up)
                up = v["nodes"][up].get("pid")
        drawn = sum(1 for _ in _walk(tree.record_tree(v)))
        assert drawn == len(v["nodes"]), kind             # each record drawn exactly once
        want = tree.PREFER[kind]                          # nothing drawn without a link of this kind
        assert all(any(r.get("via") == want for r in n.get("rels") or []) for n in v["nodes"].values()), kind


def _walk(model):
    for e in model:
        yield e
        yield from _walk(e.get("children") or [])


def test_prefer_skips_rejected_parents_and_loops_and_reads_family_words():
    nodes = {
        "a": {"caption": "A", "pid": None, "kids": ["b"], "rels": [{"at": "b", "via": "Ownership", "label": "asset"}]},
        "b": {"caption": "B", "pid": "a", "kids": [], "rels": [
            {"at": "a", "via": "Ownership", "label": "asset"},               # a owns b and b owns a: a loop
            {"at": "c", "via": "Membership", "label": "member"}]},
        "c": {"caption": "C", "pid": None, "kids": [], "rels": []},
        "d": {"caption": "D", "pid": None, "kids": [], "rels": [
            {"at": "a", "via": "Ownership", "label": "asset"}]},
        "p": {"caption": "Parent", "pid": None, "kids": [], "rels": [{"at": "k", "via": "Family", "label": "person", "record": "f1"}]},
        "k": {"caption": "Kid", "pid": None, "kids": [], "rels": [{"at": "p", "via": "Family", "label": "relative", "record": "f1"},
                                                                  {"at": "s", "via": "Family", "label": "person", "record": "f2"}]},
        "s": {"caption": "Spouse", "pid": None, "kids": [], "rels": [{"at": "k", "via": "Family", "label": "relative", "record": "f2"}]},
        "m": {"caption": "Mum", "pid": None, "kids": [], "rels": [{"at": "k", "via": "Family", "label": "relative", "record": "f3"}]},
    }
    nodes["k"]["rels"].append({"at": "m", "via": "Family", "label": "person", "record": "f3"})
    ir = {"nodes": nodes, "roots": ["a", "c", "d", "p", "k", "s", "m"], "report": {}}
    fam = {"above": ["owner", "organization"], "lateral": [], "dual": [], "governing": [], "edge_positions": {}, "exclude": []}
    from hydra import schema
    schema.ensure()
    v = tree.prefer(ir, "ownership", fam)
    assert set(v["nodes"]) == {"a", "b", "d"}                # only records with an ownership link
    assert {v["nodes"]["a"]["pid"], v["nodes"]["b"]["pid"]} & {None}    # the loop: one of the two is not moved
    assert v["nodes"]["d"]["pid"] == "a" and "moved_from" not in v["nodes"]["d"]
    from hydra.review import ids
    v = tree.prefer(ir, "ownership", fam, {ids.place_key("d", "a"): "rejected"})
    assert v["nodes"]["d"]["pid"] is None                  # a rejected parent is never used
    assert v["nodes"]["d"]["only_also"][0]["why"] == "rejected"
    roles = {"f1": "son", "f2": "spouse", "f3": "mother"}
    v = tree.prefer(ir, "family", fam, family_roles=roles)
    assert set(v["nodes"]) == {"p", "k", "s", "m"}         # no company or ownership record in a family chart
    assert v["nodes"]["k"]["pid"] in {"p", "m"}            # "son": under the person; "mother": under the relative
    assert v["nodes"]["s"]["pid"] is None                  # "spouse" stays sideways, and is drawn
    assert [x["role"] for x in v["nodes"]["k"]["sideways"]] == ["spouse"]
    other = v["nodes"]["k"]["only_also"][0]                 # the parent not drawn, worded for the one it names
    link = v["nodes"]["k"]["link"]
    assert {link, f"family: {other['role']}"} == {"family: son", "family: child (mother)"} or \
        {link, other["role"]} == {"family: child (mother)", "parent (son)"}
    assert len(set(v["report"]["groups"].values())) == 1    # one family: one group
    assert ir["nodes"]["d"]["pid"] is None                 # the read itself is untouched


def test_a_relationship_word_draws_only_those_links(tmp_path, capsys):
    root = _built(tmp_path)
    capsys.readouterr()
    assert tree.main([str(root)]) == 0
    plain = capsys.readouterr().out
    assert tree.main([str(root), "Family"]) == 0                       # a word, any capitalisation
    out = capsys.readouterr().out
    assert out != plain and "←" not in out
    assert not re.search(r"Membership|Ownership|Employment|ProjectParticipant|\(Company\)|\(Organization\)", out)
    assert "Hector Salamanca (Person)" in out                          # only ever a `relative`: still drawn
    assert "Jane Margolis (Person)   Family   child (father)" in out    # worded for the child's own line
    assert "\n\n" in out.split("\n\n", 1)[1]                            # families apart, by blank lines
    assert tree.main([str(root), "person", "family"]) == 0             # with a type
    assert tree.main([str(root), "family", "employment"]) == 0         # chained
    assert re.search(r"family employment +\d+ +\d+", capsys.readouterr().out)
    assert tree.main([str(root), "occupancy"]) == 0
    assert capsys.readouterr().out == "no occupancy links\n"
    assert tree.main([str(root), "membership", "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["counts"]["only"] == ["membership"] and doc["counts"]["links"] > 0


def test_only_draws_every_link_of_the_kinds_named_exactly_once(tmp_path):
    from hydra.review import verdicts as vd
    from hydra.structure import fold
    root = _built(tmp_path)
    ir, _ = tree._load(root, "declared")
    fam, verdicts, roles = fold.load_direction(root / layout.DIRECTION), vd.load(root)[0], tree._family_roles(root)
    for kinds in (["family"], ["membership"], ["ownership", "employment"], ["family", "membership", "directorship"]):
        v = tree.prefer(ir, kinds, fam, verdicts, roles)
        nodes = v["nodes"]
        left = v["report"]["left_out"]
        assert len(nodes) + left == len(ir["nodes"])          # the header adds up
        for rid, n0 in ir["nodes"].items():                  # every link, from the lower end (or `person`, sideways)
            for x in (y for k in kinds for y in tree._links(rid, n0, k, ir["nodes"], fam, roles)):
                if x["up"]:
                    n = nodes[rid]
                    assert n.get("pid") == x["at"] or x["at"] in {y["at"] for y in n.get("only_also") or []}, (kinds, rid, x)
                elif x["up"] is None and x["label"] == "person":
                    assert (x["at"], x["role"]) in {(y["at"], y["role"]) for y in nodes[rid]["sideways"]}, (kinds, rid)
                    assert x["at"] in nodes                    # the other end is drawn too
        drawn = list(_walk(tree.record_tree(v)))
        assert len(drawn) == len(nodes) and not any(e.get("dup") for e in drawn)       # each once
        for n in nodes.values():                             # no row listed twice
            rows = [(y["at"], y["via"], y["role"]) for y in n.get("only_also") or []]
            assert len(rows) == len(set(rows)), (kinds, n["caption"])


def test_the_first_relationship_named_wins():
    from hydra import schema
    schema.ensure()
    fam = {"above": ["employer"], "lateral": [], "dual": [], "governing": [], "edge_positions": {}, "exclude": []}
    nodes = {"mum": {"caption": "Mum", "pid": None, "kids": [], "rels": [{"at": "kid", "via": "Family", "label": "person", "record": "f"}]},
             "co": {"caption": "Co", "pid": None, "kids": [], "rels": [{"at": "kid", "via": "Employment", "label": "employer"}]},
             "kid": {"caption": "Kid", "pid": None, "kids": [], "rels": [
                 {"at": "mum", "via": "Family", "label": "relative", "record": "f"},
                 {"at": "co", "via": "Employment", "label": "employee", "role": "clerk"}]}}
    ir = {"nodes": nodes, "roots": ["mum", "co", "kid"], "report": {}}
    assert tree.prefer(ir, ["family", "employment"], fam, family_roles={"f": "son"})["nodes"]["kid"]["pid"] == "mum"
    assert tree.prefer(ir, ["employment", "family"], fam, family_roles={"f": "son"})["nodes"]["kid"]["pid"] == "co"
    v = tree.prefer(ir, ["employment", "family"], fam, family_roles={"f": "son"})
    assert v["nodes"]["kid"]["link"] == "employment: clerk"
    assert [x["at"] for x in v["nodes"]["kid"]["only_also"]] == ["mum"]           # the family link, still shown
    assert v["nodes"]["kid"]["only_also"][0]["role"] == "parent (son)"          # worded for Mum, the one it names
