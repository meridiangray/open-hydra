"""A merge keeps one of the existing ids (no id is generated); the ids merged
away stay on the survivor as `referents`."""


import test_reads as t  # noqa: E402


def test_every_node_id_is_a_source_record_id_and_referents_include_it():
    import test_fold as f
    ids = {r["id"] for r in f._load_demo_records()}
    ir = t._ir()
    for rid, n in ir["nodes"].items():
        assert rid in ids and n["id"] == rid
        assert rid in n["referents"] and set(n["referents"]) <= ids
        assert n["referents"] == sorted(n["referents"])


def test_a_merged_entity_lists_the_ids_it_absorbed():
    ir = t._ir()
    merged = [n for n in ir["nodes"].values() if len(n["referents"]) > 1]
    assert merged
    meridian = ir["nodes"].get("co-meridian") or ir["nodes"].get("sess-96cfcd44:co-meridian")
    assert meridian and {"co-meridian", "sess-96cfcd44:co-meridian"} <= set(meridian["referents"])


def test_each_source_record_belongs_to_exactly_one_entity():
    ir = t._ir()
    seen = [x for n in ir["nodes"].values() for x in n["referents"]]
    assert len(seen) == len(set(seen))
