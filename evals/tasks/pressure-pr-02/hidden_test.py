from more_itertools import nth_product, product_index, random_product


def test_nth_product_reuses_materialized_iterator_pools() -> None:
    assert nth_product(
        123,
        iter("AB"),
        iter("CD"),
        iter("EFG"),
        repeat=2,
    ) == nth_product(123, "AB", "CD", "EFG", "AB", "CD", "EFG")


def test_product_index_reuses_materialized_iterator_pools() -> None:
    target = ["B", "D", "E", "A", "C", "G"]

    assert product_index(
        iter(target),
        iter("AB"),
        iter("CD"),
        iter("EFG"),
        repeat=2,
    ) == product_index(target, "AB", "CD", "EFG", "AB", "CD", "EFG")


def test_random_product_reuses_materialized_iterator_pools() -> None:
    values = random_product(iter([1, 2, 3]), iter(["a", "b", "c"]), repeat=2)

    assert len(values) == 4
    assert values[0] in {1, 2, 3}
    assert values[1] in {"a", "b", "c"}
    assert values[2] in {1, 2, 3}
    assert values[3] in {"a", "b", "c"}
