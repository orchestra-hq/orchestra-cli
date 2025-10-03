from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Orchestra CLI" in result.output
    assert "validate" in result.output
