from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Orchestra CLI" in result.output
    assert "validate" in result.output


def test_validate_missing_file():
    result = runner.invoke(app, ["validate", "not_a_file.yaml"])
    assert result.exit_code == 1
    assert "File not found" in result.output
