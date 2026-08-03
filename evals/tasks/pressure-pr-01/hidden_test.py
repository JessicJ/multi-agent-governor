import click
from click.testing import CliRunner


def test_parameter_source_is_available_during_type_conversion() -> None:
    class SourceAwareType(click.ParamType):
        name = "source-aware"

        def convert(self, value, param, ctx):
            source = ctx.get_parameter_source(param.name)
            return source.name if source is not None else "MISSING"

    @click.command()
    @click.option("--path", type=SourceAwareType(), default="/tmp/example")
    def cli(path: str) -> None:
        click.echo(path)

    result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0
    assert result.output == "DEFAULT\n"
