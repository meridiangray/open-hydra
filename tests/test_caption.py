"""Node captions: fullest name wins on a merge, a `cap-<id>` verdict pins one."""

from hydra.shape import captions, reads  # noqa: E402


def r(*names):
    return {"id": "x1", "schema": "Person", "properties": {"name": list(names)}}


def test_fullest_name_beats_first_seen():
    assert captions.caption(r("Wallace Wright", "Wallace Hollis Wright")) == "Wallace Hollis Wright"
    assert captions.caption(r("Wallace Hollis Wright", "Wallace Wright")) == "Wallace Hollis Wright"


def test_ties_keep_first_seen():
    assert captions.caption(r("Jon Snow", "Jan Snow")) == "Jon Snow"


def test_pin_overrides_but_only_for_an_own_value():
    rec = r("Wallace Wright", "Wallace Hollis Wright")
    assert captions.caption(rec, {"cap-x1": "Wallace Wright"}) == "Wallace Wright"
    assert captions.caption(rec, {"cap-x1": "Someone Else"}) == "Wallace Hollis Wright"


def test_no_name_falls_back_to_title_then_id():
    assert captions.caption({"id": "d1", "properties": {"title": ["Doc"]}}) == "Doc"
    assert captions.caption({"id": "d2", "properties": {}}) == "d2"
