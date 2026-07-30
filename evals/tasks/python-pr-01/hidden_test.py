def test_callable_flag_value_not_instantiated() -> None:
    import click
    from click.testing import CliRunner

    class Marker:
        pass

    @click.command()
    @click.option(
        "--opt",
        "value",
        flag_value=Marker,
        type=click.UNPROCESSED,
        default=True,
    )
    def cli(value):
        click.echo(repr(value), nl=False)

    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    assert result.output == repr(Marker)
