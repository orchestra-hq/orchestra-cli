from pathlib import Path

from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app

from .test_import_pipeline import make_git_subprocess_mock


runner = CliRunner()


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
        url="https://dev.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"execution_id": "run-123"},
        status_code=200,
    )

    result = runner.invoke(app, ["run", "--alias", "demo"])
    assert result.exit_code == 0
    assert result.output.strip() == "run-123"


def test_run_with_branch_commit(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    def _assert_request(request):
        data = request.read()
        assert b"branch" in data and b"main" in data
        assert b"commit" in data and b"deadbeef" in data
        return True

    httpx_mock.add_response(
        method="POST",
        url="https://dev.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_content=_assert_request,
        json={"execution_id": "run-456"},
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
        ],
    )
    assert result.exit_code == 0
    assert result.output.strip() == "run-456"


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
        url="https://dev.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"execution_id": "run-789"},
        status_code=200,
    )

    # Simulate pressing Enter
    result = runner.invoke(app, ["run", "--alias", "demo"], input="\n")
    assert result.exit_code == 0
    assert "⚠ Uncommitted changes" in result.output
    assert "Local branch SHA does not match remote branch SHA" in result.output
    assert "Press Enter to continue" in result.output
    assert result.output.strip().endswith("run-789")


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
        url="https://dev.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"detail": "bad"},
        status_code=400,
    )

    result = runner.invoke(app, ["run", "--alias", "demo"])
    assert result.exit_code == 1
    assert "Run failed" in result.output

