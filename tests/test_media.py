"""Images and badges: linked to entities by hints.yaml rules on the entities' own
data, never read from records; `titled:` matches the titles the data states."""
import json

import pytest

from _template import copy_template  # noqa: E402
from hydra import build, layout, lint, schema  # noqa: E402

HIERARCHY = """
Leader: {}
Coordinator: {below: [Leader], titles: [captain]}
Escort: {below: [Coordinator]}
Member: {below: [Coordinator]}
"""
O = lambda i, n, s="Organization": {"id": i, "schema": s, "properties": {"name": [n]}}
E = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: [v] for k, v in p.items()}}


def P(i, n, **k):
    return {"id": i, "schema": "Person", "properties": {"name": [n], **{a: (b if isinstance(b, list) else [b])
                                                                         for a, b in k.items()}}}


ROWS = [
    O("org", "Consortium"), O("co", "Loyal", "Company"),
    P("wal", "Wallace Wright", weakAlias="Hawthorne", portrait="portraits/wal.webp", badge="old"),
    P("haw", "Hawthorne"),           # a separate person of that name (a weak alias never merges them)
    P("ana", "Ana"), E("m1", "Membership", member="ana", organization="org", role="SENTINÉL"),
    P("ben", "Ben", position="Chef"), E("m2", "Membership", member="ben", organization="org"),   # role: schema default
    P("hal", "Hal"), E("w1", "Ownership", owner="hal", asset="co", role="proprietor"),
    O("nd", "Nominee Co", "Company"), E("d1", "Directorship", director="nd", organization="co", role="nominee director"),
    P("flo", "Flo"), {"id": "post", "schema": "Position", "properties": {"name": ["Handler"], "alias": ["Cleaner"]}},
    E("o1", "Occupancy", holder="flo", post="post"),
    P("cal", "Cal", title="Captain"),                                               # an honorific, not a role
    P("fay", "Fay"), P("fred", "Fred"),
    {"id": "fam", "schema": "Family", "properties": {"person": ["fay"], "relative": ["fred"], "relationship": ["father"]}},
]
HINTS = """hints:
  - match: {name: Hawthorne}                        # 0  name only
    set:   {portrait: portraits/haw.webp}
  - match: {name|weakAlias: Hawthorne}              # 1  name or alias: the wider net, asked for
    set:   {portrait: portraits/hawthorne-sketch.webp}
  - match: {name: Wallace Wright}                      # 2  a second portrait for the same entity
    set:   {portrait: portraits/wal.webp, thumb: icons/crown.svg}
  - match: {titled: {contains: sentinel}}             # 3  accents set aside
    set:   {thumb: icons/target.svg, badge: muscle}
  - match: {titled: [chef]}                          # 4  Person.position counts; the default Member does not
    set:   {badge: chef}
  - match: {titled: Member}                          # 5  only ever a schema default here: matches nobody
    set:   {badge: member}
  - match: {titled: proprietor}                      # 6  the owner's role is the owner's, not the company's
    set:   {logo: icons/key.svg}
  - match: {any: [{titled: {contains: director}}, {name: Nobody}]}   # 7  titled nested in any:
    set:   {thumb: icons/briefcase.svg}
  - match: {titled: [Handler, Cleaner]}               # 8  a post's name and alias, post with no organization
    set:   {thumb: icons/shield.svg}
  - match: {title: Captain}                          # 9  FtM's own `title` property (the honorific)
    set:   {badge: honorific}
  - match: {titled: Captain}                         # 10 a stated role: Cal has none
    set:   {badge: role}
  - match: {titled: sentinel}                         # 11 display only: the position is ignored
    set:   {position: Leader, badge: x}
  - match: {name: Ana}                               # 12 outside resources/: refused
    set:   {portrait: ../../secret.jpg}
"""


def _archive(tmp_path, rows=ROWS, hints=HINTS):
    root = copy_template(tmp_path / "m")
    (root / layout.POSITIONS).write_text(HIERARCHY, encoding="utf-8")
    (root / layout.HINTS).write_text(hints, encoding="utf-8")
    (root / layout.COLLECTIONS_DIR / "c.json").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    for p in ("portraits/haw.webp", "portraits/wal.webp", "icons/crown.svg", "icons/target.svg"):
        f = root / layout.RESOURCES_DIR / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    build.build_archive(root, now="x")
    ir = json.loads((root / layout.PARSED_DIR / "declared.json").read_text(encoding="utf-8"))
    by = {n["caption"]: n for n in ir["nodes"].values()}
    return root, ir, by


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _archive(tmp_path_factory.mktemp("media"))


paths = lambda n, k: [x["path"] for x in n[k]]


def test_a_record_never_names_its_own_image(built):
    root, _, by = built
    wal = by["Wallace Wright"]
    assert "old" not in wal["badges"] and wal["badge"] != "old"          # the record's `badge` is not read
    assert wal["portraits"][0]["rule"] == 1                               # only rules fill images
    schema.load(root=root)
    found = {(i["code"], i["where"]) for i in lint.check(root)}
    assert ("records.display-field", "wal.portrait") in found and ("records.display-field", "wal.badge") in found


def test_images_add_up_with_where_each_came_from(built):
    _, _, by = built
    wal = by["Wallace Wright"]
    assert paths(wal, "portraits") == ["portraits/hawthorne-sketch.webp", "portraits/wal.webp"]
    assert wal["portraits"][0]["why"] == [["weakAlias", "Hawthorne"]]
    assert wal["portraits"][1] == {"path": "portraits/wal.webp", "rule": 2, "why": [["name", "Wallace Wright"]]}
    assert paths(wal, "thumbs") == ["icons/crown.svg"] and wal["logos"] == []


def test_name_means_the_name_and_alias_is_asked_for(built):
    _, _, by = built
    assert paths(by["Hawthorne"], "portraits") == ["portraits/haw.webp", "portraits/hawthorne-sketch.webp"]
    assert "portraits/haw.webp" not in paths(by["Wallace Wright"], "portraits")   # `name:` never reached his alias


def test_titled_reads_only_what_the_data_states(built):
    _, ir, by = built
    assert paths(by["Ana"], "thumbs") == ["icons/target.svg"]                   # SENTINÉL, accent set aside
    assert by["Ana"]["thumbs"][0]["why"] == [["Membership.role", "SENTINÉL"]]
    assert "chef" in by["Ben"]["badges"] and by["Ben"]["position"] is None     # stated Chef; the hint sets no position
    assert not any("member" in n["badges"] for n in ir["nodes"].values())       # a schema default is not stated
    assert "hints[5]" in ir["report"]["override_misses"]
    assert paths(by["Hal"], "logos") == ["icons/key.svg"] and by["Loyal"]["logos"] == []   # owner, not the asset
    assert paths(by["Nominee Co"], "thumbs") == ["icons/briefcase.svg"]         # a company's role; nested in any:
    assert by["Flo"]["stated_titles"] == [["Position.name", "Handler"], ["Position.alias", "Cleaner"]]
    assert paths(by["Flo"], "thumbs") == ["icons/shield.svg"]
    assert by["Fay"]["stated_titles"] == [] and by["Fred"]["stated_titles"] == []   # family words are not titles
    assert "honorific" in by["Cal"]["badges"] and "role" not in by["Cal"]["badges"]


def test_a_titled_rule_never_moves_anyone_and_bad_paths_are_refused(built):
    root, ir, by = built
    assert not any(n["position"] == "Leader" for n in ir["nodes"].values())     # rule 11 set nobody's position
    misses = ir["report"]["override_misses"]
    assert any(m.startswith("hints[11] (a `titled:` rule never sets a position") for m in misses)
    assert any(m.startswith("hints[12] (portrait '../../secret.jpg' is outside") for m in misses)
    assert by["Ana"]["portraits"] == []
    schema.load(root=root)
    found = {(i["code"], i["where"]) for i in lint.check(root)}
    assert ("hints.titled-position", "hints[11]") in found and ("hints.media-outside", "hints[12]") in found
    assert ("hints.missing-media", "hints[1]") in found                         # the sketch file is not there
    assert not any(c == "hints.unknown-property" for c, _ in found)              # `titled` is a known key


def test_rules_change_only_what_is_shown(tmp_path):
    """The same archive with no hints and with every rule above: identical tree."""
    _, a, _ = _archive(tmp_path / "with")
    _, b, _ = _archive(tmp_path / "without", hints="hints: []\n")
    keep = ("pid", "kids", "placement", "tier", "outside")
    shape = lambda ir: ({k: {x: n.get(x) for x in keep} for k, n in ir["nodes"].items()}, ir["roots"])
    assert shape(a) == shape(b)
