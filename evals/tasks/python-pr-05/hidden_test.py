def test_disabled_ctx_nested() -> None:
    from attr import validators

    assert validators.get_disabled() is False
    with validators.disabled():
        assert validators.get_disabled() is True
        with validators.disabled():
            assert validators.get_disabled() is True
        assert validators.get_disabled() is True
    assert validators.get_disabled() is False
