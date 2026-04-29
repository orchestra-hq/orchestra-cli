from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Orchestra CLI" in result.output
    assert "pipeline" in result.output


def test_pipeline_help_lists_verbs():
    result = runner.invoke(app, ["pipeline", "--help"])
    assert result.exit_code == 0
    for verb in ("validate", "import", "new", "update", "get", "run", "delete"):
        assert verb in result.output


def test_top_level_help_hides_legacy_aliases():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for legacy in (
        "fetch-pipelines",
        "create-pipeline",
        "update-pipeline",
        "delete-pipeline",
    ):
        assert legacy not in result.output


def test_legacy_aliases_still_invokable():
    # Each legacy alias is registered (hidden) so existing scripts keep working.
    # Invoking with --help is a cheap way to confirm the command exists without
    # exercising its full code path (covered in command-specific test files).
    for alias in (
        "validate",
        "import",
        "run",
        "fetch-pipelines",
        "create-pipeline",
        "update-pipeline",
        "delete-pipeline",
    ):
        result = runner.invoke(app, [alias, "--help"])
        assert result.exit_code == 0, f"Legacy alias '{alias}' is not registered"
