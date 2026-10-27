"""Node captions: fullest name wins on a merge, a `cap-<id>` verdict pins one."""

from hydra.shape import captions, reads  # noqa: E402


def r(*names):
    return {"id": "x1", "schema": "Person", "properties": {"name": list(names)}}


def test_fullest_name_beats_first_seen():
    assert captions.caption(r("Walter White", "Walter Hartwell White")) == "Walter Hartwell White"
    assert captions.caption(r("Walter Hartwell White", "Walter White")) == "Walter Hartwell White"


def test_ties_keep_first_seen():
    assert captions.caption(r("Jon Snow", "Jan Snow")) == "Jon Snow"


def test_pin_overrides_but_only_for_an_own_value():
    rec = r("Walter White", "Walter Hartwell White")
    assert captions.caption(rec, {"cap-x1": "Walter White"}) == "Walter White"
    assert captions.caption(rec, {"cap-x1": "Someone Else"}) == "Walter Hartwell White"


def test_no_name_falls_back_to_title_then_id():
    assert captions.caption({"id": "d1", "properties": {"title": ["Doc"]}}) == "Doc"
    assert captions.caption({"id": "d2", "properties": {}}) == "d2"
