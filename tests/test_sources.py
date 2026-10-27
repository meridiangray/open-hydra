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
        {"id": "wp-gus", "schema": "Article", "properties": {"title": ["Gus Fring"], "publisher": ["Wikipedia"],
                                                             "sourceUrl": ["https://en.wikipedia.org/wiki/Gus_Fring"]}},
        {"id": "wp-lph", "schema": "Article", "properties": {"title": ["Los Pollos Hermanos"]}}]), encoding="utf-8")
    rows = [{"id": "gus", "schema": "Person", "properties": {"name": ["Gustavo Fring"], "sources": ["wp-gus", "wp-lph"]}},
            {"id": "lph", "schema": "Company", "properties": {"name": ["Los Pollos Hermanos"], "sources": ["wp-lph"]}},
            {"id": "doc", "schema": "Document", "properties": {"title": ["DEA case file"]}},
            {"id": "doc~p2", "schema": "Page", "properties": {"index": ["2"], "document": ["doc"]}},
            {"id": "hank", "schema": "Person", "properties": {"name": ["Hank Schrader"], "sources": ["doc~p2"]}},
            {"id": "max", "schema": "Person", "properties": {"name": ["Max Arciniega"]}},
            {"id": "own", "schema": "Ownership", "properties": {"owner": ["gus"], "asset": ["lph"]}}]
    (root / layout.COLLECTIONS_DIR / "c.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    build.build_archive(root)
    return root


def test_the_list_keeps_source_entries_apart_from_documents_in_the_data(arch, capsys):
    from hydra import schema
    schema.load(root=arch)
    rep = sources.report(arch)
    assert [(s["title"], [c["caption"] for c in s["cited_by"]]) for s in rep["entries"]] == [
        ("Gus Fring", ["Gustavo Fring"]), ("Los Pollos Hermanos", ["Gustavo Fring", "Los Pollos Hermanos"])]
    assert rep["entries"][0]["url"] == "https://en.wikipedia.org/wiki/Gus_Fring"
    [doc] = rep["documents"]                                           # a page sits under its document
    assert (doc["title"], doc["cited_by"]) == ("DEA case file", [])
    assert [(p["title"], [c["caption"] for c in p["cited_by"]]) for p in doc["pages"]] == [
        ("DEA case file p.2", ["Hank Schrader"])]
    assert [c["caption"] for c in rep["unsourced"]] == ["Max Arciniega"]
    capsys.readouterr()
    assert sources.main([str(arch)]) == 0
    out = capsys.readouterr().out
    assert "\n  documents\n" in out and re.search(r"uncited +1\n", out)
    assert re.search(r"\n  Gus Fring \(Article\) +Wikipedia +sources-wp:wp-gus\n  │ https://\S+\n"   # the source on top
                     r"  └── Gustavo Fring \(Person\) +sources +c:gus\n", out)                      # who cites it under
    assert re.search(r"  DEA case file \(Document\) +c:doc\n  └── p.2 \(Page\) +c:doc~p2\n"
                     r"      └── Hank Schrader \(Person\) +sources +c:hank\n", out)


def test_a_type_or_a_search_keeps_to_what_those_entities_cite(arch, capsys):
    capsys.readouterr()
    assert sources.main([str(arch), "hank"]) == 0                       # a name: what it cites
    out = capsys.readouterr().out
    assert re.search(r"entities +1\n", out) and "└── p.2 (Page)" in out and "Gus Fring" not in out
    assert sources.main([str(arch), "gustavo"]) == 0                    # only his sources, only him under them
    out = capsys.readouterr().out
    assert out.count("── Gustavo Fring (Person)") == 2 and "Los Pollos Hermanos (Company)" not in out
    assert sources.main([str(arch), "PERSON", "--uncited"]) == 0       # a type; the uncited named
    out = capsys.readouterr().out
    assert re.search(r"entities +3\n", out) and "Company" not in out             # the company citing wp-lph: not a person
    assert re.search(r"uncited +1\n +Max Arciniega +Person +c:max", out)
    assert sources.main([str(arch), "wikipedia", "--format", "json"]) == 0   # no entity: the sources searched
    doc = json.loads(capsys.readouterr().out)
    assert doc["matched"] == "sources" and [s["title"] for s in doc["entries"]] == ["Gus Fring"]
    assert sources.main([str(arch), "p.2"]) == 0
    out = capsys.readouterr().out
    assert "DEA case file (Document)" in out and "└── p.2 (Page)" in out and "Hank Schrader" in out and "uncited" not in out
    assert sources.main([str(arch), "zzqq"]) == 0 and "no record or source matches" in capsys.readouterr().out


def test_the_word_sources_after_a_command_lists_only_what_it_returned(arch, capsys):
    capsys.readouterr()
    claims.main([str(arch), "gus", "sources"])
    out = capsys.readouterr().out
    listed = out.split("\nsources\n")[1]                               # what `sources` added
    assert re.search(r"entities +1\n", listed) and listed.count("sources-wp:") == 2 and "Hank" not in listed
    capsys.readouterr()
    claims.main([str(arch), "gus", "--format", "json"])
    plain = json.loads(capsys.readouterr().out)
    claims.main([str(arch), "gus", "sources", "--format", "json"])
    both = json.loads(capsys.readouterr().out)
    assert both["entities"] == plain                                   # `sources` is not part of the search
    assert [s["title"] for s in both["sources"]["entries"]] == ["Gus Fring", "Los Pollos Hermanos"]
    node.main(["find", str(arch), "hank", "sources"])
    assert "└── p.2 (Page)   c:doc~p2\n      └── Hank Schrader (Person)   sources   c:hank" in capsys.readouterr().out
    tree.main([str(arch), "gus", "sources"])                           # Gus and what is drawn under him
    out = capsys.readouterr().out
    assert re.search(r"entities +2\n", out.split("\nsources\n")[1]) and "Los Pollos Hermanos" in out


def test_a_merged_entity_says_which_of_its_records_cites(tmp_path, capsys):
    root = copy_template(tmp_path / "m")
    (root / layout.SOURCE_ENTRIES).mkdir(parents=True, exist_ok=True)
    (root / layout.SOURCE_ENTRIES / "wp.json").write_text("\n".join(json.dumps(r) for r in [
        {"id": "wp-a", "schema": "Article", "properties": {"title": ["A"]}},
        {"id": "wp-b", "schema": "Article", "properties": {"title": ["B"]}}]), encoding="utf-8")
    rows = [{"id": "walt", "schema": "Person", "properties": {"name": ["Walter Hartwell White"],
                                                            "birthDate": ["1958-09-07"], "sources": ["wp-a"]}},
            {"id": "walt2", "schema": "Person", "properties": {"name": ["Walter Hartwell White"],
                                                             "birthDate": ["1958-09-07"], "sources": ["wp-b"]}}]
    (root / layout.COLLECTIONS_DIR / "c.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    build.build_archive(root)
    capsys.readouterr()
    assert sources.main([str(root), "walter", "--ascii"]) == 0
    out = capsys.readouterr().out
    keep = re.search(r"(c:walt2?)\n\n  uncited", out).group(1)           # the id the merge kept
    other = {"c:walt": "c:walt2", "c:walt2": "c:walt"}[keep]
    own = {"c:walt": "A", "c:walt2": "B"}
    assert f"  {own[keep]} (Article)   sources-wp:wp-{own[keep].lower()}\n  \\-- Walter Hartwell White (Person)   sources   {keep}" in out
    assert f"  \\-- Walter Hartwell White (Person)   sources of {other}   {keep}" in out
