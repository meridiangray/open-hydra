"""consistency.check: facts that cannot all be true."""
from hydra import consistency, schema

P = lambda i, s, **p: {"id": i, "schema": s, "properties": {k: v if isinstance(v, list) else [v] for k, v in p.items()}}


def codes(ents):
    schema.ensure()
    return sorted(i["code"] for i in consistency.check(ents))


def test_a_female_father_and_a_younger_parent():
    ents = [P("c", "Person", name="Sultan", gender="male", birthDate="1961"),
            P("m", "Person", name="Luluwah", gender="female", birthDate="1928"),
            P("f1", "Family", person="c", relative="m", relationship="father"),
            P("k", "Person", name="Kid", birthDate="1950"),
            P("y", "Person", name="Young Dad", gender="male", birthDate="1950-06"),
            P("f2", "Family", person="k", relative="y", relationship="father")]
    assert codes(ents) == ["facts.parent-younger", "facts.relationship-gender"]


def test_dates_only_report_what_is_certain():
    ents = [P("k", "Person", name="Kid", birthDate="1951"),
            P("d", "Person", name="Dad", gender="male", birthDate="1920", deathDate="1950"),
            P("f", "Family", person="k", relative="d", relationship="father")]
    assert codes(ents) == []                                   # a father may die the year before
    ents[0]["properties"]["birthDate"] = ["1953"]
    assert codes(ents) == ["facts.parent-dead"]


def test_terms_outside_a_life_and_overlapping():
    ents = [P("a", "Person", name="Ann", birthDate="1950", deathDate="1990"),
            P("b", "Person", name="Bo", birthDate="1940"),
            P("post", "Position", name="Minister"),
            P("o1", "Occupancy", holder="a", post="post", startDate="1945", endDate="1960"),
            P("o2", "Occupancy", holder="b", post="post", startDate="1958", endDate="1970"),
            P("o3", "Occupancy", holder="a", post="post", startDate="1995")]
    assert codes(ents) == ["facts.term-outside-life", "facts.term-outside-life", "facts.terms-overlap"]


def test_own_ancestor():
    ents = [P("a", "Person", name="A"), P("b", "Person", name="B"),
            P("f1", "Family", person="a", relative="b", relationship="father"),
            P("f2", "Family", person="b", relative="a", relationship="mother")]
    assert codes(ents) == ["facts.ancestor-cycle"]
