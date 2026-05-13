from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

import orchestra_cli.src.build_pipeline as build_pipeline_module
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


def test_build_without_alias_outside_git_force_skips_alias_prompt(
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
        ["pipeline", "build", "--path", str(yaml_file), "--no-wait", "--force"],
    )

    assert result.exit_code == 0
    assert "Press Enter to accept" not in result.output
    assert "Generated alias: my-pipeline" in result.output


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


def test_build_git_backed_commits_selected_yaml_and_runs_with_detected_git_target(
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
        ("status", "--porcelain", "--", "pipe.yaml"): (0, " M pipe.yaml", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-list", "--left-right", "--count", "@{u}...HEAD"): (0, "0 0", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("add", "--", "pipe.yaml"): (0, "", ""),
        ("commit", "-m", "Migrating pipeline: 'demo'"): (0, "[main abc123] msg", ""),
        ("push",): (0, "", ""),
        ("rev-parse", "HEAD"): (0, "abc123", ""),
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
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"pipeline_id": "pipeline-id", "branch": "main", "commit": "abc123"},
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
            "override-branch",
            "--commit",
            "override-commit",
            "--no-wait",
        ],
        input="\n",
    )

    assert result.exit_code == 0
    assert "Using git-backed build target branch 'main' at commit abc123" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (pipeline_id: pipeline-id), run id: {mock_pipeline_run_id}",
    )


def test_build_git_backed_push_failure_can_retry_on_new_branch(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")
    suggested_branch = "orchestra-migrate-pipeline-ABC123"
    monkeypatch.setattr(build_pipeline_module, "_suggest_migration_branch_name", lambda: suggested_branch)

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    current_branch = "main"
    head_commit = "1111111"

    def run_git(args, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        nonlocal current_branch
        nonlocal head_commit
        key = tuple(args[1:])
        if key == ("rev-parse", "--show-toplevel"):
            return Result(0, str(tmp_path), "")
        if key == ("remote", "get-url", "origin"):
            return Result(0, "git@github.com:org/repo.git", "")
        if key == ("status", "--porcelain"):
            return Result(0, "", "")
        if key == ("status", "--porcelain", "--", "pipe.yaml"):
            return Result(0, " M pipe.yaml", "")
        if key == ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
            return Result(0, "origin/main", "")
        if key == ("rev-list", "--left-right", "--count", "@{u}...HEAD"):
            return Result(0, "0 0", "")
        if key == ("rev-parse", "--abbrev-ref", "HEAD"):
            return Result(0, current_branch, "")
        if key == ("add", "--", "pipe.yaml"):
            return Result(0, "", "")
        if key == ("commit", "-m", "Migrating pipeline: 'demo'"):
            head_commit = "abc1234"
            return Result(0, "[main abc1234] commit", "")
        if key == ("push",):
            return Result(1, "", "remote: push blocked by branch protection")
        if key == ("checkout", "-b", suggested_branch):
            current_branch = suggested_branch
            return Result(0, "", "")
        if key == ("push", "-u", "origin", suggested_branch):
            return Result(0, "", "")
        if key == ("rev-parse", "HEAD"):
            return Result(0, head_commit, "")

        return Result(1, "", f"unhandled git command: {key}")

    import subprocess

    monkeypatch.setattr(subprocess, "run", run_git)

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
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "pipeline_id": "pipeline-id",
            "branch": suggested_branch,
            "commit": "abc1234",
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--path", str(yaml_file), "--no-wait"],
        input="\n\n\n\n",
    )

    assert result.exit_code == 0
    assert "branch protection" in result.output
    assert suggested_branch in result.output
    assert f"Started pipeline (pipeline_id: pipeline-id), run id: {mock_pipeline_run_id}" in result.output


def test_build_git_backed_force_auto_accepts_branch_retry(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")
    suggested_branch = "orchestra-migrate-pipeline-FORCE1"
    monkeypatch.setattr(build_pipeline_module, "_suggest_migration_branch_name", lambda: suggested_branch)

    def fail_input() -> str:
        raise AssertionError("input should not be called when --force is set")

    monkeypatch.setattr("builtins.input", fail_input)

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    current_branch = "main"
    head_commit = "2222222"

    def run_git(args, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        nonlocal current_branch
        nonlocal head_commit
        key = tuple(args[1:])
        if key == ("rev-parse", "--show-toplevel"):
            return Result(0, str(tmp_path), "")
        if key == ("remote", "get-url", "origin"):
            return Result(0, "git@github.com:org/repo.git", "")
        if key == ("status", "--porcelain"):
            return Result(0, "", "")
        if key == ("status", "--porcelain", "--", "pipe.yaml"):
            return Result(0, " M pipe.yaml", "")
        if key == ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"):
            return Result(0, "origin/main", "")
        if key == ("rev-list", "--left-right", "--count", "@{u}...HEAD"):
            return Result(0, "0 0", "")
        if key == ("rev-parse", "--abbrev-ref", "HEAD"):
            return Result(0, current_branch, "")
        if key == ("add", "--", "pipe.yaml"):
            return Result(0, "", "")
        if key == ("commit", "-m", "Migrating pipeline: 'demo'"):
            head_commit = "def5678"
            return Result(0, "[main def5678] commit", "")
        if key == ("push",):
            return Result(1, "", "remote: push blocked by branch protection")
        if key == ("checkout", "-b", suggested_branch):
            current_branch = suggested_branch
            return Result(0, "", "")
        if key == ("push", "-u", "origin", suggested_branch):
            return Result(0, "", "")
        if key == ("rev-parse", "HEAD"):
            return Result(0, head_commit, "")

        return Result(1, "", f"unhandled git command: {key}")

    import subprocess

    monkeypatch.setattr(subprocess, "run", run_git)

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
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "pipeline_id": "pipeline-id",
            "branch": suggested_branch,
            "commit": "def5678",
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "build", "--path", str(yaml_file), "--no-wait", "--force"],
    )

    assert result.exit_code == 0
    assert "Press Enter" not in result.output
    assert suggested_branch in result.output


def test_suggest_migration_branch_name_format(monkeypatch):
    monkeypatch.setattr(build_pipeline_module.random, "choices", lambda _chars, k: list("ABC123"))
    assert build_pipeline_module._suggest_migration_branch_name() == "orchestra-migrate-pipeline-ABC123"


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
