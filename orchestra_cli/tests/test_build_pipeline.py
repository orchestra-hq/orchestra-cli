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


def test_build_updates_existing_draft_and_starts_version(
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
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
        json={"id": "pipeline-id", "latestVersionNumber": 12},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"branch": "main", "commit": "deadbeef", "versionNumber": 12},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "pipeline",
            "build",
            "--alias",
            "demo",
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
    assert "updated as version 12" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}",
    )


def test_build_creates_draft_on_missing_alias(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
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
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        json={"detail": "not found"},
        status_code=404,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "alias": "demo",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
        json={"id": "pipeline-id", "currentVersionNumber": 3},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"versionNumber": 3},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["build", "--alias", "demo", "--path", str(yaml_file), "--no-wait"],
    )

    assert result.exit_code == 0
    assert "created as version 3" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}",
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
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        json={"id": "pipeline-id"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--alias", "demo", "--path", str(yaml_file), "--no-wait"],
    )

    assert result.exit_code == 1
    assert "did not include draft version number" in result.output


def test_build_reports_non_404_update_error(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
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
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        json={"detail": "bad"},
        status_code=400,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--alias", "demo", "--path", str(yaml_file), "--no-wait"],
    )

    assert result.exit_code == 1
    assert "Build failed" in result.output
