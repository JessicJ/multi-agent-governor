def test_formatting_usage_error_help_hint() -> None:
    import click
    from click.testing import CliRunner

    @click.group(context_settings={"help_option_names": ["-h", "--help"]})
    def cli():
        pass

    @cli.command()
    @click.option("--host", "-h")
    @click.argument("required_arg")
    def child(required_arg, host):
        pass

    result = CliRunner().invoke(cli, ["child"])
    assert result.exit_code == 2
    assert "Try 'cli child --help' for help." in result.output.splitlines()
