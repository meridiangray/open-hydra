"""`<prefix>:<local id>` namespacing: manifest-chosen or name-derived prefixes, existing
prefixes kept, same-collection id pointers rewritten, nothing else touched."""


import test_fold as f  # noqa: E402
import test_reads as t  # noqa: E402
from hydra import ingest as prefixes  # noqa: E402
from hydra.ingest import source_of  # noqa: E402
from hydra.shape import reads, rules  # noqa: E402
from hydra.structure import fold  # noqa: E402


def test_default_tag_is_a_valid_never_reserved_source_name():
    assert prefixes.default_prefix("Fairbank Condensed") == "fairbank-condensed"
    assert prefixes.default_prefix("manifest") == "manifest-c"
    assert prefixes.default_prefix("") == "collection"
    for name in ("consortium", "Dce Files!", "a/b"):
        assert source_of(prefixes.default_prefix(name) + ":x") == prefixes.default_prefix(name)


def test_manifest_choice_wins_and_defaults_are_stored_back():
    man = {"format": 2, "collections": {"consortium": {"file": "consortium.json", "prefix": "ald"}}}
    got = prefixes.resolve_prefixes(["consortium", "dce"], man)
    assert got == {"consortium": "ald", "dce": "dce"}
    out = prefixes.manifest_with_prefixes(man, got)
    assert out["collections"]["consortium"]["prefix"] == "ald" and out["collections"]["dce"]["prefix"] == "dce"
    assert out["collections"]["consortium"]["file"] == "consortium.json"
    assert man["collections"]["consortium"]["prefix"] == "ald" and "dce" not in man["collections"]


def test_an_invalid_manifest_tag_falls_back_to_the_default():
    assert prefixes.resolve_prefixes(["x"], {"collections": {"x": {"prefix": "Bad Prefix!"}}}) == {"x": "x"}


def test_ids_get_the_collection_tag_and_existing_prefixes_are_kept():
    recs = [{"id": "p1", "schema": "Person", "_collection": "alpha", "properties": {"name": ["A"]}},
            {"id": "s9:p2", "schema": "Person", "_collection": "alpha", "properties": {"name": ["B"]}}]
    out, rep = prefixes.prefix_records(recs)
    assert [r["id"] for r in out] == ["alpha:p1", "s9:p2"]
    assert recs[0]["id"] == "p1"                       # input untouched
    assert rep["prefixes"] == {"alpha": "alpha"}


def test_same_collection_id_pointers_are_rewritten_but_names_are_not():
    recs = [{"id": "d1", "schema": "Document", "_collection": "c", "properties": {"title": ["d1"]}},
            {"id": "e1", "schema": "Documentation", "_collection": "c",
             "properties": {"document": ["d1"], "entity": ["Wallace Wright"]}}]
    out, _ = prefixes.prefix_records(recs)
    e = next(r for r in out if r["id"] == "c:e1")
    assert e["properties"]["document"] == ["c:d1"] and e["properties"]["entity"] == ["Wallace Wright"]
    assert next(r for r in out if r["id"] == "c:d1")["properties"]["title"] == ["d1"]


def test_a_pointer_to_another_collections_record_takes_that_collections_tag():
    recs = [{"id": "d1", "schema": "Document", "_collection": "docs", "properties": {}},
            {"id": "e1", "schema": "Documentation", "_collection": "notes",
             "properties": {"document": ["d1"]}}]
    out, rep = prefixes.prefix_records(recs)
    assert next(r for r in out if r["id"] == "notes:e1")["properties"]["document"] == ["docs:d1"]
    assert rep["ambiguous_pointers"] == []


def test_an_id_held_by_several_other_collections_is_reported_not_guessed():
    recs = [{"id": "d1", "schema": "Document", "_collection": "a", "properties": {}},
            {"id": "d1", "schema": "Document", "_collection": "b", "properties": {}},
            {"id": "e1", "schema": "Documentation", "_collection": "c",
             "properties": {"document": ["d1"]}}]
    out, rep = prefixes.prefix_records(recs)
    assert next(r for r in out if r["id"] == "c:e1")["properties"]["document"] == ["d1"]
    assert rep["ambiguous_pointers"] == [{"record": "e1", "prop": "document", "value": "d1",
                                          "collections": ["a", "b"]}]


def test_two_collections_with_one_tag_and_local_id_collide_loudly():
    recs = [{"id": "x", "schema": "Person", "_collection": "a", "properties": {}},
            {"id": "x", "schema": "Person", "_collection": "b", "properties": {}}]
    man = {"collections": {"a": {"prefix": "shared"}, "b": {"prefix": "shared"}}}
    _, rep = prefixes.prefix_records(recs, man)
    assert rep["collisions"] == [{"id": "shared:x", "collections": ["a", "b"]}]
    _, ok = prefixes.prefix_records(recs)
    assert ok["collisions"] == []


def test_the_demo_corpus_builds_the_same_graph_once_tagged():
    f._load()
    recs = f._load_demo_records()
    prefixed, rep = prefixes.prefix_records(recs)
    assert not rep["collisions"]
    fam = fold.load_direction(f.DIRECTION)
    g = rules.compile_rules(None, None, direction=fam)
    src = reads.build_reads(recs, g, direction=fam, params_dir=f.PARAMS)
    new = reads.build_reads(prefixed, g, direction=fam, params_dir=f.PARAMS)
    assert len(new["nodes"]) == len(src["nodes"]) and len(new["roots"]) == len(src["roots"])
    assert all(source_of(i) for i in new["nodes"])
    assert new["report"]["provenance"] == src["report"]["provenance"]
    wal = next(n for n in new["nodes"].values() if n["caption"] == "Wallace Hollis Wright")
    assert wal["id"].endswith(":p-wal") and "hawthorne:p-wal" in wal["referents"]
    swal = src["nodes"]["p-wal"]
    assert new["nodes"][wal["pid"]]["caption"] == src["nodes"][swal["pid"]]["caption"]
    cap_of = lambda ir: {n["caption"].split(":")[-1]: ir["nodes"][n["pid"]]["caption"].split(":")[-1]
                         for n in ir["nodes"].values() if n["pid"]}
    assert cap_of(new) == cap_of(src)
    assert {k: v["prefix"] for k, v in rep["manifest"]["collections"].items()} == rep["prefixes"]
    assert rep["ambiguous_pointers"] == []
