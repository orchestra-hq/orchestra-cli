from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app
from tests.conftest import make_git_subprocess_mock

runner = CliRunner()
mock_pipeline_run_id = "798d7121-6809-4148-aecb-26740cfabdf1"
mock_api_key = "fake-key"


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", mock_api_key)
    monkeypatch.setenv("BASE_URL", "")


def test_run_success_simple(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    # Mock git repo to trigger no warnings
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": mock_pipeline_run_id},
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        status_code=200,
    )

    result = runner.invoke(app, ["run", "--alias", "demo", "--no-wait"])
    assert result.exit_code == 0
    assert (
        result.output.strip()
        == f"Starting pipeline (alias: demo)\nStarted pipeline (alias: demo), run id: {mock_pipeline_run_id}"  # noqa: E501
    )


def test_run_with_branch_commit(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"branch": "main", "commit": "deadbeef"},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=201,
    )

    result = runner.invoke(
        app,
        [
            "run",
            "--alias",
            "demo",
            "--branch",
            "main",
            "--commit",
            "deadbeef",
            "--no-wait",
        ],
    )
    assert result.exit_code == 0
    assert (
        result.output.strip()
        == f"Starting pipeline (alias: demo)\nStarted pipeline (alias: demo), run id: {mock_pipeline_run_id}"  # noqa: E501
    )


def test_run_warnings_prompt(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, " M file.txt\n", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-parse", "HEAD"): (0, "aaaa", ""),
        ("rev-parse", "@{u}"): (0, "bbbb", ""),
        ("status", "-sb"): (0, "## main...origin/main [behind 1]", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    # Simulate pressing Enter
    result = runner.invoke(app, ["run", "--alias", "demo", "--no-wait"], input="\n")
    assert result.exit_code == 0
    assert "⚠ Uncommitted changes" in result.output
    assert "Local branch SHA does not match remote branch SHA" in result.output
    assert "Press Enter to continue" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}",
    )


def test_run_api_error(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "bad"},
        status_code=400,
    )

    result = runner.invoke(app, ["run", "--alias", "demo", "--no-wait"])
    assert result.exit_code == 1
    assert "Run failed" in result.output


def test_run_wait_success(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    # Mock git repo to trigger no warnings
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    # Start run
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    # Polling: RUNNING -> SUCCEEDED
    httpx_mock.add_response(
        method="GET",
        url=f"https://app.getorchestra.io/api/engine/public/pipeline_runs/{mock_pipeline_run_id}/status",
        json={"runStatus": "RUNNING", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://app.getorchestra.io/api/engine/public/pipeline_runs/{mock_pipeline_run_id}/status",
        json={"runStatus": "SUCCEEDED", "pipelineName": "demo"},
        status_code=200,
    )

    result = runner.invoke(app, ["run", "--alias", "demo", "--wait"])
    assert result.exit_code == 0
    # Last printed line should be the run id
    assert result.output.strip().splitlines()[0] == "Starting pipeline (alias: demo)"
    assert (
        result.output.strip().splitlines()[1]
        == f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}"
    )  # noqa: E501
    assert "Invalid status value: RUNNING" not in result.output
    assert result.output.strip().splitlines()[-2] == "✅ Pipeline succeeded"
    assert result.output.strip().splitlines()[-1] == mock_pipeline_run_id


def test_run_wait_failed(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": "run-xyz"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-xyz/status",
        json={"runStatus": "RUNNING", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-xyz/status",
        json={"runStatus": "FAILED", "pipelineName": "demo"},
        status_code=200,
    )

    result = runner.invoke(app, ["run", "--alias", "demo", "--wait"])
    assert result.exit_code == 1
    assert "Invalid status value: RUNNING" not in result.output
    assert "status FAILED" in result.output
    assert "/pipeline-runs/run-xyz/lineage" in result.output


def test_run_wait_warning(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": "run-warn"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-warn/status",
        json={"runStatus": "WARNING", "pipelineName": "demo"},
        status_code=200,
    )

    result = runner.invoke(app, ["run", "--alias", "demo", "--wait"])
    assert result.exit_code == 0
    assert result.output.strip().splitlines()[-1] == "run-warn"
