from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from orchestra_cli.src.cli import app
from orchestra_cli.utils.pipeline_selector import (
    PipelineSelector,
    generate_alias_from_path,
    resolve_pipeline_selector,
)
from tests.conftest import make_git_subprocess_mock

runner = CliRunner()


def test_alias_takes_precedence_over_pipeline_id_and_path(tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")

    selector = resolve_pipeline_selector(
        alias="demo",
        pipeline_id="pipeline-id",
        path=yaml_file,
    )

    assert selector == PipelineSelector(alias="demo")


def test_pipeline_id_takes_precedence_over_path(tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")

    selector = resolve_pipeline_selector(
        alias=None,
        pipeline_id="pipeline-id",
        path=yaml_file,
    )

    assert selector == PipelineSelector(pipeline_id="pipeline-id")


def test_path_inside_git_resolves_repository_and_yaml_path(monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    yaml_file = repo_root / "pipelines" / "pipe.yaml"
    yaml_file.parent.mkdir()
    yaml_file.write_text("name: demo\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    selector = resolve_pipeline_selector(alias=None, pipeline_id=None, path=yaml_file)

    assert selector == PipelineSelector(repository="org/repo", yaml_path="pipelines/pipe.yaml")


def test_generate_alias_from_path_slugifies_filename():
    assert generate_alias_from_path(Path("My Pipeline.yaml")) == "my-pipeline"


def test_pipeline_id_can_be_disallowed(capsys):
    with pytest.raises(typer.Exit):
        resolve_pipeline_selector(
            alias=None,
            pipeline_id="pipeline-id",
            path=None,
            allow_pipeline_id=False,
        )

    assert "Passing pipeline IDs is not supported for this command" in capsys.readouterr().out


def test_create_command_does_not_accept_pipeline_id():
    result = runner.invoke(app, ["pipeline", "new", "--pipeline-id", "pipeline-id"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_build_style_resolve_generates_alias_from_path_without_alias_arg(
    monkeypatch,
    tmp_path: Path,
):
    """Same mode as ``pipeline build`` when creating a draft: path only, no repo+yaml selector."""
    repo_root = tmp_path
    yaml_file = repo_root / "pipelines" / "custom_name.yaml"
    yaml_file.parent.mkdir(parents=True)
    yaml_file.write_text("name: demo\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr("builtins.input", lambda: "")

    selector = resolve_pipeline_selector(
        None,
        None,
        yaml_file,
        allow_pipeline_id=False,
        use_git_path_selector=False,
    )

    assert selector == PipelineSelector(alias="custom-name")
