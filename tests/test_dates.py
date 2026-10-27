"""dates.py — a direct port of the old engine's span/overlap logic. Tests
mirror what reads.py relied on (same functions, same semantics)."""


from hydra import dates  # noqa: E402


def test_bounds_year_month_day():
    assert dates.bounds("2008") == ("2008-01-01", "2008-12-31")
    assert dates.bounds("2008-06") == ("2008-06-01", "2008-06-31")
    assert dates.bounds("2008-06-15") == ("2008-06-15", "2008-06-15")
    assert dates.bounds("") is None
    assert dates.bounds(None) is None


def test_span_multi_valued_and_open_ended():
    assert dates.span(["2009"], ["2010"]) == ("2009-01-01", "2010-12-31")
    assert dates.span(["2009"], []) == ("2009-01-01", None)  # still ongoing
    assert dates.span([], []) == (None, None)  # fully unknown


def test_overlaps_unknown_bound_counts_as_overlapping():
    """Matches the old engine's stated philosophy exactly: "unknown means
    can't tell, which counts as overlapping so that undated evidence stays
    ambiguous" -- never silently treated as sequential."""
    assert dates.overlaps((None, None), ("2020-01-01", "2020-12-31"))
    assert dates.overlaps(("2009-01-01", None), ("2015-01-01", "2015-06-01"))


def test_overlaps_true_when_ranges_intersect():
    assert dates.overlaps(("2009-01-01", "2010-12-31"), ("2010-06-01", "2011-01-01"))


def test_overlaps_false_when_ranges_are_fully_disjoint_and_known():
    assert not dates.overlaps(("2005-01-01", "2005-12-31"), ("2010-01-01", "2010-12-31"))


def test_key_start_sorts_unknown_first():
    assert dates.key_start((None, None)) == ""
    assert dates.key_start(("2010-01-01", None)) == "2010-01-01"
    assert sorted([dates.key_start((None, None)), dates.key_start(("2010-01-01", None))]) == \
        ["", "2010-01-01"]
