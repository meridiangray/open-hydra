"""sources.py: `hydra-ctl sources`, and the word `sources` after claims, node find and tree."""
import json
import re

import pytest

from _template import copy_template  # noqa: E402
from hydra import build, claims, layout, sources, tree  # noqa: E402
from hydra.cli import node  # noqa: E402


@pytest.fixture(scope="module")
def arch(tmp_path_factory):
    """Two Wikipedia-style entries, entities citing them, a page of a document in
    the data, and one entity citing nothing."""
    root = copy_template(tmp_path_factory.mktemp("s") / "a")
    (root / layout.SOURCE_ENTRIES).mkdir(parents=True, exist_ok=True)
    (root / layout.SOURCE_ENTRIES / "wp.json").write_text("\n".join(json.dumps(r) for r in [
        {"id": "wp-gid", "schema": "Article", "properties": {"title": ["Gid Fairbank"], "publisher": ["Wikipedia"],
                                                             "sourceUrl": ["https://en.wikipedia.org/wiki/Gid_Fairbank"]}},
        {"id": "wp-lph", "schema": "Article", "properties": {"title": ["Loyal Provisions"]}}]), encoding="utf-8")
    rows = [{"id": "gid", "schema": "Person", "properties": {"name": ["Gideon Fairbank"], "sources": ["wp-gid", "wp-lph"]}},
            {"id": "lph", "schema": "Company", "properties": {"name": ["Loyal Provisions"], "sources": ["wp-lph"]}},
            {"id": "doc", "schema": "Document", "properties": {"title": ["DCE case file"]}},
            {"id": "doc~p2", "schema": "Page", "properties": {"index": ["2"], "document": ["doc"]}},
            {"id": "hal", "schema": "Person", "properties": {"name": ["Hal Sharpe"], "sources": ["doc~p2"]}},
            {"id": "max", "schema": "Person", "properties": {"name": ["Max Arden"]}},
            {"id": "own", "schema": "Ownership", "properties": {"owner": ["gid"], "asset": ["lph"]}}]
    (root / layout.COLLECTIONS_DIR / "c.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    build.build_archive(root)
    return root


def test_the_list_keeps_source_entries_apart_from_documents_in_the_data(arch, capsys):
    from hydra import schema
    schema.load(root=arch)
    rep = sources.report(arch)
    assert [(s["title"], [c["caption"] for c in s["cited_by"]]) for s in rep["entries"]] == [
        ("Gid Fairbank", ["Gideon Fairbank"]), ("Loyal Provisions", ["Gideon Fairbank", "Loyal Provisions"])]
    assert rep["entries"][0]["url"] == "https://en.wikipedia.org/wiki/Gid_Fairbank"
    [doc] = rep["documents"]                                           # a page sits under its document
    assert (doc["title"], doc["cited_by"]) == ("DCE case file", [])
    assert [(p["title"], [c["caption"] for c in p["cited_by"]]) for p in doc["pages"]] == [
        ("DCE case file p.2", ["Hal Sharpe"])]
    assert [c["caption"] for c in rep["unsourced"]] == ["Max Arden"]
    capsys.readouterr()
    assert sources.main([str(arch)]) == 0
    out = capsys.readouterr().out
    assert "\n  documents\n" in out and re.search(r"uncited +1\n", out)
    assert re.search(r"\n  Gid Fairbank \(Article\) +Wikipedia +sources-wp:wp-gid\n  │ https://\S+\n"   # the source on top
                     r"  └── Gideon Fairbank \(Person\) +sources +c:gid\n", out)                      # who cites it under
    assert re.search(r"  DCE case file \(Document\) +c:doc\n  └── p.2 \(Page\) +c:doc~p2\n"
                     r"      └── Hal Sharpe \(Person\) +sources +c:hal\n", out)


def test_a_type_or_a_search_keeps_to_what_those_entities_cite(arch, capsys):
    capsys.readouterr()
    assert sources.main([str(arch), "hal"]) == 0                       # a name: what it cites
    out = capsys.readouterr().out
    assert re.search(r"entities +1\n", out) and "└── p.2 (Page)" in out and "Gid Fairbank" not in out
    assert sources.main([str(arch), "gideon"]) == 0                    # only his sources, only him under them
    out = capsys.readouterr().out
    assert out.count("── Gideon Fairbank (Person)") == 2 and "Loyal Provisions (Company)" not in out
    assert sources.main([str(arch), "PERSON", "--uncited"]) == 0       # a type; the uncited named
    out = capsys.readouterr().out
    assert re.search(r"entities +3\n", out) and "Company" not in out             # the company citing wp-lph: not a person
    assert re.search(r"uncited +1\n +Max Arden +Person +c:max", out)
    assert sources.main([str(arch), "wikipedia", "--format", "json"]) == 0   # no entity: the sources searched
    doc = json.loads(capsys.readouterr().out)
    assert doc["matched"] == "sources" and [s["title"] for s in doc["entries"]] == ["Gid Fairbank"]
    assert sources.main([str(arch), "p.2"]) == 0
    out = capsys.readouterr().out
    assert "DCE case file (Document)" in out and "└── p.2 (Page)" in out and "Hal Sharpe" in out and "uncited" not in out
    assert sources.main([str(arch), "zzqq"]) == 0 and "no record or source matches" in capsys.readouterr().out


def test_the_word_sources_after_a_command_lists_only_what_it_returned(arch, capsys):
    capsys.readouterr()
    claims.main([str(arch), "gid", "sources"])
    out = capsys.readouterr().out
    listed = out.split("\nsources\n")[1]                               # what `sources` added
    assert re.search(r"entities +1\n", listed) and listed.count("sources-wp:") == 2 and "Hal" not in listed
    capsys.readouterr()
    claims.main([str(arch), "gid", "--format", "json"])
    plain = json.loads(capsys.readouterr().out)
    claims.main([str(arch), "gid", "sources", "--format", "json"])
    both = json.loads(capsys.readouterr().out)
    assert both["entities"] == plain                                   # `sources` is not part of the search
    assert [s["title"] for s in both["sources"]["entries"]] == ["Gid Fairbank", "Loyal Provisions"]
    node.main(["find", str(arch), "hal", "sources"])
    assert "└── p.2 (Page)   c:doc~p2\n      └── Hal Sharpe (Person)   sources   c:hal" in capsys.readouterr().out
    tree.main([str(arch), "gid", "sources"])                           # Gid and what is drawn under him
    out = capsys.readouterr().out
    assert re.search(r"entities +2\n", out.split("\nsources\n")[1]) and "Loyal Provisions" in out


def test_a_merged_entity_says_which_of_its_records_cites(tmp_path, capsys):
    root = copy_template(tmp_path / "m")
    (root / layout.SOURCE_ENTRIES).mkdir(parents=True, exist_ok=True)
    (root / layout.SOURCE_ENTRIES / "wp.json").write_text("\n".join(json.dumps(r) for r in [
        {"id": "wp-a", "schema": "Article", "properties": {"title": ["A"]}},
        {"id": "wp-b", "schema": "Article", "properties": {"title": ["B"]}}]), encoding="utf-8")
    rows = [{"id": "wal", "schema": "Person", "properties": {"name": ["Wallace Hollis Wright"],
                                                            "birthDate": ["1958-09-07"], "sources": ["wp-a"]}},
            {"id": "wal2", "schema": "Person", "properties": {"name": ["Wallace Hollis Wright"],
                                                             "birthDate": ["1958-09-07"], "sources": ["wp-b"]}}]
    (root / layout.COLLECTIONS_DIR / "c.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    build.build_archive(root)
    capsys.readouterr()
    assert sources.main([str(root), "wallace", "--ascii"]) == 0
    out = capsys.readouterr().out
    keep = re.search(r"(c:wal2?)\n\n  uncited", out).group(1)           # the id the merge kept
    other = {"c:wal": "c:wal2", "c:wal2": "c:wal"}[keep]
    own = {"c:wal": "A", "c:wal2": "B"}
    assert f"  {own[keep]} (Article)   sources-wp:wp-{own[keep].lower()}\n  \\-- Wallace Hollis Wright (Person)   sources   {keep}" in out
    assert f"  \\-- Wallace Hollis Wright (Person)   sources of {other}   {keep}" in out
