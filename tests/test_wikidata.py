"""wikidata: items shaped as the API returns them, read into FtM records by the shipped map;
the unread report; and `hydra-ctl wikidata import` end to end with the network replaced."""
import json

import pytest

from hydra.cli import init as hinit
from hydra.cli import wikidata as cmd
from hydra.wikidata import api, mapping, nominate, read, report


def snak(value, kind="wikibase-entityid"):
    v = {"id": value} if kind == "wikibase-entityid" else value
    return {"mainsnak": {"snaktype": "value", "datavalue": {"type": kind, "value": v}}, "rank": "normal"}


def when(t, precision):
    return snak({"time": t, "precision": precision}, "time")


def item(q, name, claims=None, desc=None, lang="en"):
    return {"id": q, "labels": {lang: {"language": lang, "value": name}},
            "descriptions": {"en": {"value": desc}} if desc else {}, "claims": claims or {}}


ITEMS = {
    "Q42": item("Q42", "Douglas Adams", desc="writer", lang="mul", claims={
        "P31": [snak("Q5")],
        "P569": [when("+1952-03-11T00:00:00Z", 11)],
        "P570": [when("+2001-00-00T00:00:00Z", 9)],
        "P21": [snak("Q6581097")],
        "P27": [snak("Q145"), snak("Q2184")],
        "P26": [{**snak("Q9"), "qualifiers": {"P580": [{"datavalue": {"type": "time", "value": {"time": "+1991-11-25T00:00:00Z", "precision": 11}}}]}}],
        "P1412": [snak("Q1860")],
        "P2048": [snak({"amount": "+1.96"}, "quantity")],
        "P214": [snak("113230702", "string")],
        "P5008": [snak("Q1")],
    }),
    "Q145": item("Q145", "United Kingdom", {"P297": [snak("GB", "string")]}),
    "Q2184": item("Q2184", "Soviet-ish"),                         # no ISO code
    "Q6581097": item("Q6581097", "male"),
    "Q1860": item("Q1860", "English", {"P220": [snak("eng", "string")]}),
    "Q9": item("Q9", "Jane Belson", {"P31": [snak("Q5")]}),
}
RULES = mapping.load(None)


def convert(items=ITEMS, qids=("Q42",)):
    return read.convert(items, list(qids), RULES)


def test_fields_read_by_their_ftm_type():
    recs, _ = convert()
    p = next(r for r in recs if r["id"] == "Q42")["properties"]
    assert p["name"] == ["Douglas Adams"]                      # the `mul` label stands in for `en`
    assert p["upstream"] == ["wikidata:Q42"]
    assert p["birthDate"] == ["1952-03-11"] and p["deathDate"] == ["2001"]
    assert p["gender"] == ["male"] and p["citizenship"] == ["gb"] and p["spokenLanguage"] == ["eng"]
    assert p["summary"] == ["writer"]


def test_country_without_iso_code_is_counted_not_guessed():
    recs, rep = convert()
    assert rep["left_out"]["countries with no ISO code"]["count"] == 1
    assert "Soviet-ish" not in json.dumps(recs)


def test_claim_becomes_relationship_with_dates_and_a_keyed_stub():
    recs, rep = convert()
    fam = next(r for r in recs if r["schema"] == "Family")
    assert fam["properties"] == {"person": ["Q42"], "relative": ["Q9"], "relationship": ["spouse"],
                                 "startDate": ["1991-11-25"]}
    stub = next(r for r in recs if r["id"] == "Q9")
    assert stub["schema"] == "Person" and stub["properties"]["upstream"] == ["wikidata:Q9"]
    assert rep["mapped"][("P26", "Family")]["count"] == 1


def test_deprecated_claims_skipped_and_preferred_win():
    it = item("Q1", "X", {"P31": [snak("Q5")], "P569": [
        {**when("+1900-01-01T00:00:00Z", 11), "rank": "deprecated"},
        {**when("+1901-01-01T00:00:00Z", 11), "rank": "normal"},
        {**when("+1902-01-01T00:00:00Z", 11), "rank": "preferred"}]})
    recs, _ = convert({"Q1": it}, ["Q1"])
    assert recs[0]["properties"]["birthDate"] == ["1902-01-01"]


def test_decade_and_circa_dates_keep_their_qualifier():
    it = item("Q1", "X", {"P31": [snak("Q5")], "P569": [when("+1950-00-00T00:00:00Z", 8)],
                          "P570": [{**when("+1990-05-06T00:00:00Z", 11), "qualifiers": {"P1480": [{"datavalue": {"type": "wikibase-entityid", "value": {"id": read.CIRCA}}}]}}]})
    rec = convert({"Q1": it}, ["Q1"])[0][0]
    assert rec["properties"]["birthDate"] == ["1950"] and rec["_meta"]["approx"] == {"birthDate": "decade", "deathDate": "circa"}


def test_class_the_map_lacks_is_left_out_and_said():
    recs, rep = convert({"Q2": item("Q2", "A thing", {"P31": [snak("Q999")]})}, ["Q2"])
    assert recs == [] and "items whose class the map has no schema for" in rep["left_out"]


def test_unread_claims_are_recorded_except_ignored_and_mapped():
    _, rep = convert()
    assert set(pid for _, pid in rep["unread"]) == {"P2048", "P214"}          # P5008 is ignored, the rest mapped


def test_unread_report_groups_ids_apart_and_suggests_by_type_and_name():
    _, rep = convert()
    props = {"P2048": {"label": "height", "description": "", "datatype": "quantity", "formatter": ""},
             "P214": {"label": "VIAF cluster ID", "description": "", "datatype": "external-id", "formatter": ""}}
    g = nominate.unread_report(rep["unread"], props, RULES)
    assert [r["pid"] for r in g["fits"]] == ["P2048"] and g["fits"][0]["fields"] == ["Person.height"]
    assert [r["pid"] for r in g["ids"]] == ["P214"] and g["other"] == []


def test_a_web_address_can_only_be_website_or_source_url():
    got = nominate.suggest("Company", {"label": "official shop URL", "datatype": "url"})
    assert [f for f, _ in got] == ["website", "sourceUrl"]


def test_the_shipped_map_names_only_fields_the_schema_has():
    from hydra import schema
    schema.ensure()
    for sname, table in RULES["properties"].items():
        fields = schema.resolve(sname)["props"]
        for pid, spec in table.items():
            to = spec if isinstance(spec, str) else (spec or {}).get("to")
            assert to is None or to in fields, f"{sname}.{pid} -> {to}"
    for sname, rels in RULES["relationships"].items():
        for pid, spec in rels.items():
            assert spec["schema"] in schema.SCHEMA and spec["target"] in schema.SCHEMA


def test_reports_print_without_colour_when_piped():
    recs, rep = convert()
    text = "\n".join(report.imported("collections/wikidata.json", len(recs), 1, rep, {"P569": "date of birth"}, ["Q42"]))
    assert "COPIED INTO FIELDS" in text and "Person.birthDate" in text and "P569 date of birth" in text
    assert "\x1b" not in text


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(api, "fetch", lambda qids, cache, refs=True: ITEMS)
    monkeypatch.setattr(api, "describe", lambda pids, cache: {p: {"label": p, "description": "", "datatype": "string", "formatter": ""} for p in pids})


def test_import_writes_a_collection_that_merges_by_key(tmp_path, offline):
    root = tmp_path / "case"
    hinit.create(root, name="case", prefix="c")
    (root / "collections" / "casefile.json").write_text(json.dumps([
        {"id": "memo", "schema": "Person", "properties": {"name": ["D. N. Adams"], "upstream": ["wikidata:Q42"]}}]), encoding="utf-8")
    lines = []
    assert cmd.main(["import", str(root), "Q42"], say=lines.append) == 0
    assert (root / "collections" / "wikidata.json").is_file()
    assert any("Imported" in l for l in lines)
    assert any("Rebuilt" in l and "4 records, 3 entities" in l for l in lines)       # memo joined Douglas Adams by the key
    with pytest.raises(SystemExit, match="exists"):
        cmd.main(["import", str(root), "Q42", "--no-build"], say=lines.append)
    assert cmd.main(["import", str(root), "Q42", "--no-build", "--force"], say=lines.append) == 0


def test_import_of_a_bad_id_is_refused_before_any_request(tmp_path, offline):
    root = tmp_path / "case"
    hinit.create(root, name="case", prefix="c")
    with pytest.raises(SystemExit, match="not an item id"):
        cmd.main(["import", str(root), "Douglas"], say=print)
