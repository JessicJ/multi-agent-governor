def test_predicate_never_receives_internal_marker() -> None:
    from more_itertools import locate

    seen = []

    def predicate(*items):
        assert all(isinstance(item, int) for item in items)
        seen.append(items)
        return False

    assert list(locate([1, 2], predicate, window_size=3)) == []
    assert seen == [(1, 2)]
