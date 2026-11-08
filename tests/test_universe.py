"""The universe layer end to end, on three small archives:

    case  (self)      Cy Vale [idNumber X-1], Bo Grant b.1961, Di Moss, Vale Holdings, a directorship
    reg   (embedded)  Cy Vale [idNumber X-1] b.1970, Bo Grant b.1960, Di Moss
    api   (linked)    "C. Vale", pinned upstream to Cy's H
"""
import json
import shutil
import zipfile

import pytest
import yaml

from hydra import build as hbuild
from hydra import layout
from hydra.cli import init as hinit
from hydra.cli import main as cli
from hydra.cli import pack as hpack
from hydra.cli.answer import set_verdict
from hydra.universe import build, hid, layer, members, review, table
from hydra.wiki import site

P = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: v if isinstance(v, list) else [v] for k, v in p.items()}}


def archive(path, name, records, universe=False):
    hinit.create(path, name=name, prefix=name, universe=universe)
    (path / "collections" / f"{name}.json").write_text(json.dumps(records), encoding="utf-8")
    return path


@pytest.fixture
def uni(tmp_path):
    case = archive(tmp_path / "case", "case", [
        P("doc1", "Document", title="Case file", fileName="case.pdf"),
        P("a1", "Person", name="Cy Vale", idNumber="X-1", sources="doc1"),
        P("b1", "Person", name="Bo Grant", birthDate="1961"),
        P("d1", "Person", name="Di Moss"),
        P("o1", "Company", name="Vale Holdings"),
        P("dir1", "Directorship", director="Cy Vale", organization="Vale Holdings", role="director", startDate="2001"),
    ], universe=True)
    reg = archive(tmp_path / "reg", "reg", [
        P("r9", "Person", name="Cy Vale", idNumber="X1", birthDate="1970"),
        P("r7", "Person", name="Bo Grant", birthDate="1960"),
        P("r5", "Person", name="Di Moss", nationality="gb"),
    ])
    members.embed(case, reg, "reg")
    return case, tmp_path


def pages_of(root):
    return {p["body"]: p for p in layer.read_parsed(root, "pages.jsonl")}


def by_title(root, title):
    return [p for p in pages_of(root).values() if p["title"] == title]


def test_hid_format():
    b = hid.derive("u1", "self/x:1")
    assert hid.fmt(b, "d", 4) == f"H-d4-{b}" and hid.parse(f"H-d4-{b}") == ("d", 4, b)
    assert hid.parse(f"H-{b}") == (None, None, b) and hid.body(b) == b
    assert hid.split_pin(f"pollard:H-p0-{b}") == ("pollard", b) and hid.pin_key(f"H-c0-{b}") == f"H-{b}"
    assert hid.flag_names(hid.flag_value({"stale", "redirected"})) == ["redirected", "stale"]
    with pytest.raises(ValueError):
        hid.parse("H-x0-" + b)


def test_init_gives_every_archive_a_universe_of_one(tmp_path):
    root = archive(tmp_path / "a", "a", [P("p1", "Person", name="Ann Lee")], universe=True)
    assert layer.read_manifest(root)["members"] == {"self": {}}
    hbuild.build_archive(root)                                         # the archive build gives Hs
    rows = layer.read_parsed(root, "canon.jsonl")
    assert len(rows) == 1 and rows[0]["h"].startswith("H-c0-") and rows[0]["members"] == ["self/a:p1"]
    assert not (root / layout.UNIVERSE_PARSED / "pages.jsonl").exists()   # pages: universe build, wiki


def test_identifier_merges_across_members_names_do_not(uni):
    case, _ = uni
    r = build.build(case)
    cy = by_title(case, "Cy Vale")
    assert len(cy) == 1 and {m.split("/")[0] for m in cy[0]["members"]} == {"self", "reg"}
    bo = by_title(case, "Bo Grant")
    assert len(bo) == 2 and bo[0]["also"] == [bo[1]["body"]]
    assert {p["qualifier"] for p in bo} == {"born 1960", "born 1961"}          # what tells them apart
    assert r["counts"]["proposed"] == 2
    vh = by_title(case, "Vale Holdings")[0]
    assert any(x.get("other") == cy[0]["body"] and x["role"] == "director" for x in vh["relations"])
    assert [d["title"] for c in cy[0]["citations"] for d in c["docs"]] == ["Case file"]


def test_merge_reject_split_and_flags(uni):
    case, _ = uni
    build.build(case)
    bo = by_title(case, "Bo Grant")
    review.merge(case, bo[0]["h"], bo[1]["h"])
    di = by_title(case, "Di Moss")
    review.reject(case, di[0]["h"], f"H-{di[1]['body']}")
    build.build(case)
    bo = by_title(case, "Bo Grant")
    assert len(bo) == 1 and bo[0]["state"] == "d" and bo[0]["h"].startswith("H-d2-")
    assert bo[0]["flags"] == ["conflict"] and bo[0]["disagree"] == ["birthDate"]
    di = by_title(case, "Di Moss")
    assert len(di) == 2 and not di[0]["also"] and not di[1]["also"]
    assert all(r["h"][3] == "0" for r in table.load(case).values())          # the table never stores flags
    review.split(case, bo[0]["h"], ["reg/reg:r7"])
    build.build(case)
    assert len(by_title(case, "Bo Grant")) == 2


def test_published_h_survives_a_new_anchor_and_an_upstream_pin(uni):
    case, tmp = uni
    build.build(case)
    out, emitted = site.site(case, tmp / "site")
    assert review.publish(case, emitted) == len(emitted)
    cy = by_title(case, "Cy Vale")[0]
    reg2 = archive(tmp / "reg2", "reg", [P("r9", "Person", name="Cy Vale", idNumber="X1", birthDate="1970"),
                                         P("a0", "Person", name="Cy V.", idNumber="X-1")])
    members.refresh(case, "reg", reg2)
    api = archive(tmp / "api", "api", [P("q1", "Person", name="C. Vale", upstream=f"Pollard:H-p0-{cy['body']}")])
    doc = layer.read_manifest(case)
    doc["title"] = "Pollard"
    layer.write_manifest(case, doc)
    members.link(case, api, "api")
    build.build(case)
    now = by_title(case, "Cy Vale")
    assert len(now) == 1 and now[0]["body"] == cy["body"] and now[0]["state"] == "p"
    assert "api/api:q1" in now[0]["members"] and "C. Vale" in now[0]["aliases"]


def test_redirect_and_orphan(uni):
    case, tmp = uni
    api = archive(tmp / "api", "api", [P("z1", "Person", name="Zed Only")])
    members.link(case, api, "api")
    build.build(case)
    _, emitted = site.site(case, tmp / "site")
    review.publish(case, emitted)
    build.build(case)
    bo = by_title(case, "Bo Grant")
    keep = review.merge(case, bo[0]["h"], bo[1]["h"])
    gone = next(b["body"] for b in bo if b["body"] != keep)
    shutil.rmtree(api)
    r = build.build(case)
    assert any("api" in w for w in r["warnings"])
    w = site.Wiki(case)
    assert w.status(gone) == (301, keep) and w.status(f"H-p0-{keep}") == (301, keep)
    zed = next(x for x in layer.read_parsed(case, "canon.jsonl") if "orphaned" in x["flags"])
    assert zed["title"] == "Zed Only" and w.status(zed["body"])[0] == 410     # the table kept its title


def test_a_caption_pin_by_h_survives_a_new_survivor(tmp_path):
    """The drift case: a pin written on one record id is lost when a richer record merges
    in and becomes the survivor; by H it holds."""
    root = archive(tmp_path / "a", "a", [P("p1", "Person", name=["Ann Lee", "A. Lee"])], universe=True)
    hbuild.build_archive(root)
    body = layer.read_parsed(root, "canon.jsonl")[0]["body"]
    rows = table.load(root)
    table.promote(rows, body, "p", anchor="self/a:p1", members=["self/a:p1"])
    table.save(root, rows)
    set_verdict(root / layout.VERDICTS, f"cap-H-{body}", "A. Lee")
    (root / "collections" / "reg.json").write_text(json.dumps([P("r1", "Person", name=["Ann Lee"], idNumber="9",
                                                                  birthDate="1970", nationality="gb")]), encoding="utf-8")
    recs = json.loads((root / "collections" / "a.json").read_text(encoding="utf-8"))
    recs[0]["properties"]["idNumber"] = ["9"]
    (root / "collections" / "a.json").write_text(json.dumps(recs), encoding="utf-8")
    hbuild.build_archive(root)                                       # reg:r1 is richer: it survives the merge
    nodes = json.loads((root / layout.READS["declared"]).read_text(encoding="utf-8"))["nodes"]
    (nid, node), = ((k, v) for k, v in nodes.items() if v["schema"] == "Person")
    assert nid != "a:p1" and node["caption"] == "A. Lee"


@pytest.mark.proof
def test_not_lists_keep_an_archives_own_records_apart(tmp_path):
    root = archive(tmp_path / "a", "a", [P("p1", "Person", name="Ann Lee"), P("p2", "Person", name="Ann Lee")],
                   universe=True)
    m = root / "hydra.yaml"
    m.write_text(m.read_text(encoding="utf-8") + "same_name: merge\n", encoding="utf-8")
    hbuild.build_archive(root)
    assert len(layer.read_parsed(root, "canon.jsonl")) == 1             # merged by name
    m.write_text(m.read_text(encoding="utf-8").replace("same_name: merge\n", ""), encoding="utf-8")
    hbuild.build_archive(root)
    a, b = layer.read_parsed(root, "canon.jsonl")
    review.reject(root, a["h"], b["h"])
    m.write_text(m.read_text(encoding="utf-8") + "same_name: merge\n", encoding="utf-8")
    hbuild.build_archive(root)
    assert len(layer.read_parsed(root, "canon.jsonl")) == 2             # the universe's `not` holds


def test_pack_carries_both_layers_and_hydra_reads_it(uni):
    case, tmp = uni
    build.build(case)
    out, _, _ = hpack.pack(case, tmp / "pollard.hydra", with_parsed=False)
    index = json.loads(zipfile.ZipFile(out).read(hpack.PACK_INDEX))
    assert index["format"] == 1 and index["layers"] == ["archive", "universe"] and "reg.hydra" in index["members"]
    assert not any(n.startswith(layout.UNIVERSE_PARSED) for n in index["files"])
    dest, _ = hpack.unpack(out, tmp / "opened")
    build.build(dest)
    assert by_title(dest, "Cy Vale")


def test_cli_universe_and_wiki(uni, capsys):
    case, tmp = uni
    assert cli(["universe", str(case), "build"]) == 0
    assert cli(["universe", str(case), "review"]) == 0
    assert "2 pairs share a name" in capsys.readouterr().out
    bo = by_title(case, "Bo Grant")
    assert cli(["universe", str(case), "merge", bo[0]["h"], bo[1]["body"], "--by", "test"]) == 0
    assert [r["by"] for r in table.load(case).values()] == ["test"]       # who decided, recorded
    assert cli(["wiki", str(case), "site", "-o", str(tmp / "s"), "--publish"]) == 0
    assert (tmp / "s" / "index.html").is_file() and any((tmp / "s").glob("e-*.html"))
    assert all(r["state"] in ("p", "d") for r in table.load(case).values())


def test_export_by_h_and_publish(tmp_path):
    from hydra.cli import export as hexport
    root = archive(tmp_path / "a", "a", [P("p1", "Person", name="Ann Lee"), P("o1", "Company", name="Lee Ltd"),
                                         P("d1", "Directorship", director="Ann Lee", organization="Lee Ltd")],
                   universe=True)
    hbuild.build_archive(root)
    rep = hexport.export(root, "ftm", tmp_path / "e.jsonl", ids="h", publish=True)
    ents = [json.loads(l) for l in (tmp_path / "e.jsonl").read_text(encoding="utf-8").splitlines()]
    ann = next(e for e in ents if e["schema"] == "Person")
    d = next(e for e in ents if e["schema"] == "Directorship")
    assert ann["id"].startswith("H-") and "a:p1" in ann["referents"] and d["properties"]["director"] == [ann["id"]]
    assert rep["published"] == 2 and {r["state"] for r in table.load(root).values()} == {"p"}
