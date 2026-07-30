def test_pre_init_kw_only_work_with_defaults() -> None:
    import attr

    observed = None

    @attr.define
    class Example:
        value: int = attr.field(kw_only=True, default=3)

        def __attrs_pre_init__(self, *, value):
            nonlocal observed
            observed = value

    instance = Example()
    assert observed == instance.value == 3
