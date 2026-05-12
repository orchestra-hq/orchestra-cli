from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app
from tests.conftest import make_git_subprocess_mock

runner = CliRunner()
mock_api_key = "fake-key"
mock_pipeline_run_id = "798d7121-6809-4148-aecb-26740cfabdf1"


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", mock_api_key)
    monkeypatch.setenv("BASE_URL", "")


def test_build_updates_existing_draft_and_starts_version_by_repo_path(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "pipeline_id": "pipeline-id",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
        json={"id": "pipeline-id", "latestVersionNumber": 12},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "pipeline_id": "pipeline-id",
            "branch": "main",
            "commit": "deadbeef",
            "versionNumber": 12,
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "pipeline",
            "build",
            "--path",
            str(yaml_file),
            "--branch",
            "main",
            "--commit",
            "deadbeef",
            "--no-wait",
        ],
    )

    assert result.exit_code == 0
    assert "Updating draft pipeline (pipeline_id: pipeline-id)" in result.output
    assert "updated as version 12" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (pipeline_id: pipeline-id), run id: {mock_pipeline_run_id}",
    )


def test_build_creates_draft_when_pipeline_is_missing(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "not found"},
        status_code=404,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "alias": "pipe",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
        json={"id": "pipeline-id", "currentVersionNumber": 3},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"pipeline_id": "pipeline-id", "versionNumber": 3},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--path", str(yaml_file), "--no-wait"],
        input="\n",
    )

    assert result.exit_code == 0
    assert "Generated alias: pipe" in result.output
    assert "Creating draft pipeline (alias: pipe)" in result.output
    assert "created as version 3" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (pipeline_id: pipeline-id), run id: {mock_pipeline_run_id}",
    )


def test_build_creates_draft_with_force_skips_alias_prompt(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    def fail_input() -> str:
        raise AssertionError("input should not be called when --force is set")

    monkeypatch.setattr("builtins.input", fail_input)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "not found"},
        status_code=404,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "alias": "pipe",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
        json={"id": "pipeline-id", "currentVersionNumber": 3},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"pipeline_id": "pipeline-id", "versionNumber": 3},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--path", str(yaml_file), "--no-wait", "--force"],
    )

    assert result.exit_code == 0
    assert "Press Enter to accept" not in result.output
    assert "Generated alias: pipe" in result.output
    assert "Creating draft pipeline (alias: pipe)" in result.output


def test_build_without_alias_outside_git_generates_alias_from_path(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "My Pipeline.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        make_git_subprocess_mock(
            {("rev-parse", "--show-toplevel"): (1, "", "fatal: not a git repo")},
        ),
    )

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=my-pipeline",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "not found"},
        status_code=404,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "alias": "my-pipeline",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
        json={"id": "pipeline-id", "currentVersionNumber": 7},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"pipeline_id": "pipeline-id", "versionNumber": 7},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--path", str(yaml_file), "--no-wait"],
        input="\n",
    )

    assert result.exit_code == 0
    assert "generating a pipeline alias from --path" in result.output
    assert "Generated alias: my-pipeline" in result.output
    assert "Creating draft pipeline (alias: my-pipeline)" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (pipeline_id: pipeline-id), run id: {mock_pipeline_run_id}",
    )


def test_build_fails_without_version_number(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"id": "pipeline-id", "storage_provider": "ORCHESTRA", "alias": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json={"id": "pipeline-id"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--alias", "demo", "--path", str(yaml_file), "--no-wait"],
    )

    assert result.exit_code == 1
    assert "did not include draft version number" in result.output


def test_build_fails_when_pipeline_lookup_returns_error_status(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "upstream error"},
        status_code=503,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--alias", "demo", "--path", str(yaml_file), "--no-wait"],
    )

    assert result.exit_code == 1
    assert "Build failed with status 503" in result.output
    assert "did not include draft version number" not in result.output
    assert "existing pipeline metadata did not include" not in result.output


def test_build_reports_git_backed_pipeline_as_unsupported(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "storage_provider": "GITHUB"},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "build", "--path", str(yaml_file), "--no-wait"])

    assert result.exit_code == 1
    assert "git-backed pipelines are not yet supported" in result.output


def test_build_uses_zero_latest_version_number(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "storage_provider": "ORCHESTRA", "alias": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "pipeline_id": "pipeline-id",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
        json={"id": "pipeline-id", "latestVersionNumber": 0},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"pipeline_id": "pipeline-id", "versionNumber": 0},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--alias", "demo", "--path", str(yaml_file), "--no-wait"],
    )

    assert result.exit_code == 0
    assert "updated as version 0" in result.output
