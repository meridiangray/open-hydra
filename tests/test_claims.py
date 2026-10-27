"""claims.py: look up entities by name (or id) and type, grouped by property;
and the summary."""
import json
import re
import shutil
from pathlib import Path

import pytest


import test_fold as t  # noqa: E402
from _template import copy_template  # noqa: E402
from hydra import build, claims, layout  # noqa: E402

CORPUS2 = Path(__file__).resolve().parent / "corpus2" / "collections"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    r = copy_template(tmp_path_factory.mktemp("c") / "a")
    for f in t.DEMO.glob("*.json"):
        (r / layout.COLLECTIONS_DIR / f.name).write_bytes(f.read_bytes())
    build.build_archive(r, now="x")
    return r


@pytest.fixture(scope="module")
def corpus2(tmp_path_factory):
    r = copy_template(tmp_path_factory.mktemp("c2") / "a")
    for f in CORPUS2.glob("*.json"):
        shutil.copy(f, r / layout.COLLECTIONS_DIR / f.name)
    build.build_archive(r, now="x")
    return r


def _json(capsys, *argv):
    capsys.readouterr()
    assert claims.main([*map(str, argv), "--format", "json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_a_name_finds_entities_grouped_by_property(demo, capsys):
    got = _json(capsys, demo, "walter white", "--type", "person")         # any capitalisation
    assert {b["id"] for b in got[:2]} == {"heisenberg:p-walt", "dea:p-waltjr"}   # names first...
    assert len(got) > 2                                                   # ...then other fields naming him
    walt = next(b for b in got if b["id"] == "heisenberg:p-walt")
    assert [v["value"] for v in walt["props"]["weakAlias"]] == ["Walt", "Heisenberg", "Mr. Lambert"]
    assert walt["props"]["name"][0]["collections"] == ["heisenberg"]


def test_type_includes_subtypes_and_exact_narrows(demo, capsys):
    assert [b["schema"] for b in _json(capsys, demo, "pollos", "--type", "Organization")][0] == "Company"
    assert [b["id"] for b in _json(capsys, demo, "pollos", "--type", "Person")] == ["cartel:p-max"]   # a field mentions it
    assert _json(capsys, demo, "walter white", "--exact") == []
    assert [b["id"] for b in _json(capsys, demo, "Walter Hartwell White", "--exact")] == ["heisenberg:p-walt"]


def test_an_id_or_merged_away_id_finds_the_entity(corpus2, capsys):
    assert [b["id"] for b in _json(capsys, corpus2, "leaks:c-holding")] == ["registry:c-holding"]


def test_spelling_variants_are_not_a_disagreement(corpus2, capsys):
    holding = _json(capsys, corpus2, "registry:c-holding")[0]
    name, reg = holding["props"]["name"], holding["props"]["registrationNumber"]
    assert [{k: v[k] for k in ("value", "also", "collections")} for v in name] == [
        {"value": "Nordwind Holding AG", "also": ["NORDWIND HOLDING AG"], "collections": ["leaks", "registry"]}]
    assert [x["record"] for x in name[0]["sources"]] == ["leaks:c-holding", "registry:c-holding"]
    assert reg[0]["value"] == "CHE-101.202.303" and reg[0]["also"] == ["CHE101202303"]
    assert holding["disputed"] == []
    ports = _json(capsys, corpus2, "registry:c-ports")[0]
    assert ports["props"]["name"][0]["value"] == "Société Générale des Ports Méridionaux SA"
    s = _json(capsys, "summary", corpus2)
    assert s["disputed"] == 0 and "corroborated" not in s


def test_no_name_shows_the_summary(demo, capsys):
    claims.main(["summary", str(demo)])
    want = capsys.readouterr().out
    claims.main([str(demo)])
    assert capsys.readouterr().out == want


def test_a_schema_name_is_the_type(demo, capsys):
    claims.main(["summary", str(demo), "--type", "Organization"])
    want = capsys.readouterr().out
    claims.main([str(demo), "Organization"])
    assert capsys.readouterr().out == want
    lines = want.splitlines()
    start = next(i for i, l in enumerate(lines) if l.split()[:2] == ["collection", "claims"]) + 1
    schemas = [line.split()[2] for line in lines[start:] if len(line.split()) >= 4]   # the middle table
    assert "Organization" in schemas and "Person" not in schemas
    assert {b["schema"] for b in _json(capsys, demo, "company", "pollos")} == {"Company"}   # the type, as a word
    assert _json(capsys, demo, "pollos", "COMPANY") == _json(capsys, demo, "company", "pollos")   # in any order


def test_summary_and_text_output(demo, capsys):
    s = _json(capsys, "summary", demo)
    assert s["claims"] == sum(s["collections"].values()) and len(s["disputed_examples"]) == min(s["disputed"], 10)
    capsys.readouterr()
    claims.main([str(demo), "heisenberg", "--type", "Person"])
    out = capsys.readouterr().out
    assert re.search(r"Walter Hartwell White +Person +heisenberg:p-walt", out) and "weakAlias" in out


def test_only_a_distinct_field_is_a_disagreement(tmp_path, capsys):
    root = copy_template(tmp_path / "s")
    P = lambda i, **p: {"id": i, "schema": "Person", "properties": {k: [v] for k, v in p.items()}}
    for c, r in (("registry", P("a", name="Jonathan Smith", passportNumber="P1", birthDate="1970-01-01")),
                 ("press", P("c", name="J. Smithe", passportNumber="P1", birthDate="1971"))):
        (root / layout.COLLECTIONS_DIR / f"{c}.json").write_text(json.dumps([r]), encoding="utf-8")
    build.build_archive(root, now="x")
    from hydra.review import ids
    (root / layout.VERDICTS).write_text(f"{ids.merge_key('registry:a', 'press:c')}: confirmed\n", encoding="utf-8")
    build.build_archive(root, now="x")
    block = _json(capsys, root, "smith")[0]
    assert block["disputed"] == ["birthDate"]          # two names are not a conflict; two birth dates are


# ---- trails: value -> record -> evidence, and the review it took part in ------


def test_every_claim_names_its_record_and_a_surviving_entity(demo):
    rows = claims.load(demo)
    assert rows and all(r.get("record") for r in rows)
    nodes = json.loads((demo / ".hydra" / "parsed" / "declared.json").read_text(encoding="utf-8"))["nodes"]
    merged_away = {x for n in nodes.values() for x in n.get("referents") or [] if x != n["id"]}
    assert not merged_away & {r["entity"] for r in rows}             # filed under survivors only


def test_a_value_traces_to_its_record_and_the_page_its_proof_names(demo, capsys):
    (cartel,) = _json(capsys, demo, "Juarez Cartel", "--exact", "--type", "Organization")
    (src,) = cartel["props"]["jurisdiction"][0]["sources"]
    assert src["record"] == "cartel:org-cartel"
    assert src["evidence"] and src["evidence"][0].endswith("p.3") and "CASE FILE" in src["evidence"][0]
    assert any(d.endswith("p.3") for d in cartel["documented_in"])


def test_a_value_shows_the_review_rows_it_took_part_in(tmp_path, capsys):
    """A ~ B on a name, B ~ C on B's alias, A ~ C (a shared email) rejected for
    clashing dates: each
    date names the record that clashes and the contradiction; each shared name
    names the link it made in the chain."""
    from hydra.review import ids
    r = copy_template(tmp_path / "acme")
    (r / layout.COLLECTIONS_DIR / "a.json").write_text(json.dumps([
        {"id": "a", "schema": "Company", "properties": {"name": ["Acme Ltd"], "incorporationDate": ["1990"],
                                                       "email": ["x@acme.example"]}},
        {"id": "b", "schema": "Company", "properties": {"name": ["Acme Ltd"], "alias": ["Acme Trading"]}},
        {"id": "c", "schema": "Company", "properties": {"name": ["Acme Trading"], "incorporationDate": ["2015"],
                                                       "email": ["x@acme.example"]}}]), encoding="utf-8")
    build.build_archive(r, now="x")
    rejected = ids.merge_key("a:a", "a:c")
    (r / layout.VERDICTS).write_text(f"{rejected}: rejected\n", encoding="utf-8")
    build.build_archive(r, now="x")
    (acme,) = _json(capsys, r, "Acme", "--type", "Company")
    by = {v["value"]: v["review"] for v in acme["props"]["incorporationDate"]}
    (r1990,) = by["1990"]
    assert r1990["kind"] == "contradiction" and r1990["of"] == rejected and r1990["theirs"] == ["2015"]
    assert r1990["with"].startswith("a:c")
    joined = [x for v in acme["props"]["name"] for x in v["review"]]
    assert joined and all(x["kind"] == "joined-despite-rejection" and x["of"] == rejected for x in joined)
    capsys.readouterr()
    assert claims.main([str(r), "Acme"]) == 0
    text = capsys.readouterr().out
    assert re.search(rf"merged +rejected +{rejected}", text) and re.search(rf"joined +rejected +{rejected}", text)


def test_the_search_reaches_other_fields(tmp_path, capsys):
    root = copy_template(tmp_path / "f")
    rows = [{"id": "a", "schema": "Person", "properties": {"name": ["Ann Lee"], "birthPlace": ["Tikrit"]}},
            {"id": "b", "schema": "Person", "properties": {"name": ["Tikrit Hassan"]}},
            {"id": "c", "schema": "Company", "properties": {"name": ["Acme"], "address": ["1 Road, Tikrit"]}}]
    (root / "collections" / "f.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    build.build_archive(root)
    assert [b["id"] for b in _json(capsys, root, "tikrit")] == ["f:b", "f:a", "f:c"]   # the name, then fields
    assert [b["id"] for b in _json(capsys, root, "person", "tikrit")] == ["f:b", "f:a"]
    assert [b["id"] for b in _json(capsys, root, "tikrit", "--exact")] == ["f:a"]      # equal to a value


def test_upstream_referents_are_kept_found_and_exported(tmp_path, capsys):
    from hydra.cli import export, node
    root = copy_template(tmp_path / "u")
    rows = [{"id": "NK-1", "schema": "Person", "referents": ["europol-ouali-karim", "interpol-red-1"],
             "datasets": ["eu_europol_wanted"], "properties": {"name": ["Karim Ouali"]}}]
    (root / "collections" / "eu.json").write_text(json.dumps(rows[0]), encoding="utf-8")
    build.build_archive(root)
    (block,) = _json(capsys, root, "ouali")
    assert {"europol-ouali-karim", "interpol-red-1"} <= set(block["referents"])
    claims.main([str(root), "ouali"])
    out = capsys.readouterr().out
    assert re.search(r"merged upstream +europol-ouali-karim\n +interpol-red-1", out)
    assert node.find(root, "interpol-red-1", field="id")[0]["id"] == "eu:NK-1"          # found by an upstream id
    out = tmp_path / "x.ftm.jsonl"
    export.main([str(root), "--format", "ftm", "-o", str(out)])
    ent = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert {"europol-ouali-karim", "interpol-red-1"} <= set(ent["referents"])          # written back out


def test_a_search_skips_link_fields_and_a_word_can_start_a_name(tmp_path, capsys):
    root = copy_template(tmp_path / "g")
    (root / layout.SOURCE_ENTRIES).mkdir(parents=True, exist_ok=True)
    (root / layout.SOURCE_ENTRIES / "wp.json").write_text(json.dumps(
        {"id": "wp-gus", "schema": "Article", "properties": {"title": ["Gus Fring"]}}), encoding="utf-8")
    rows = [{"id": "gus", "schema": "Person", "properties": {"name": ["Gustavo Fring"], "sources": ["wp-gus"]}},
            {"id": "max", "schema": "Person", "properties": {"name": ["Max Arciniega"], "sources": ["wp-gus"]}}]
    (root / "collections" / "c.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    build.build_archive(root)
    assert [b["caption"] for b in _json(capsys, root, "gus")] == ["Gustavo Fring"]   # not Max, who cites wp-gus
    assert _json(capsys, root, "gu") == []                                         # 3 letters at least
