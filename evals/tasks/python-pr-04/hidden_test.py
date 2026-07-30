def test_empty_reversed() -> None:
    from more_itertools import numeric_range

    assert list(reversed(numeric_range(0))) == []
