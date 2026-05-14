from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app
from orchestra_cli.utils import git as git_module
from tests.conftest import make_git_subprocess_mock

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")
    monkeypatch.setenv("BASE_URL", "")


def test_update_success_default_no_publish(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json={"id": "pipeline-id"},
        status_code=200,
        match_json={
            "pipeline_id": "pipeline-id",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
    )

    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 0
    assert "updated successfully" in result.output
    assert "https://app.getorchestra.io/pipelines/pipeline-id/edit" in result.output


def test_update_publish_flag(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json={"id": "pipeline-id"},
        status_code=200,
        match_json={
            "pipeline_id": "pipeline-id",
            "data": {"name": "demo", "version": 1},
            "published": True,
            "storage_provider": "ORCHESTRA",
        },
    )

    result = runner.invoke(
        app,
        ["update-pipeline", "--alias", "demo", "--path", str(yaml_file), "--publish"],
    )
    assert result.exit_code == 0
    assert "updated successfully" in result.output
    assert "https://app.getorchestra.io/pipelines/pipeline-id/edit" in result.output


def test_update_success_by_pipeline_id(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?pipeline_id=pipeline-id",
        json={"id": "pipeline-id", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json={"id": "pipeline-id"},
        status_code=200,
        match_json={
            "pipeline_id": "pipeline-id",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
    )

    result = runner.invoke(
        app,
        ["pipeline", "update", "--pipeline-id", "pipeline-id", "--path", str(yaml_file)],
    )
    assert result.exit_code == 0
    assert "updated successfully" in result.output


def test_update_path_inside_git_uses_repository_selector(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    repo_root = tmp_path
    yaml_file = repo_root / "pipelines" / "pipe.yaml"
    yaml_file.parent.mkdir()
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipelines%2Fpipe.yaml",
        json={"id": "pipeline-id", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json={"id": "pipeline-id"},
        status_code=200,
        match_json={
            "pipeline_id": "pipeline-id",
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(app, ["pipeline", "update", "--path", str(yaml_file)], input="\n")

    assert result.exit_code == 0
    assert "Generated alias" not in result.output
    assert "updated successfully" in result.output


def test_update_missing_api_key(monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")

    monkeypatch.delenv("ORCHESTRA_API_KEY", raising=False)
    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "ORCHESTRA_API_KEY is not set" in result.output


def test_update_invalid_yaml(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [oops\n")

    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(bad)])
    assert result.exit_code == 1
    assert "Invalid YAML" in result.output


def test_update_schema_validation_error(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"detail": [{"loc": ["root"], "msg": "bad"}]},
        status_code=400,
    )

    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "Validation failed" in result.output


def test_update_orchestra_backed_api_error(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json={"detail": "Only orchestra-backed pipelines can be updated via this endpoint."},
        status_code=400,
    )

    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "Update failed" in result.output
    assert "Only orchestra-backed pipelines can be updated via this endpoint." in result.output


def test_update_fails_when_pipeline_lookup_returns_error_status(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"detail": "upstream error"},
        status_code=503,
    )

    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "Update failed with status 503" in result.output


def test_update_git_backed_uses_current_git_target_without_upsert(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain", "--", "pipe.yaml"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-list", "--left-right", "--count", "@{u}...HEAD"): (0, "0 0", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
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
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "update", "--path", str(yaml_file)])

    assert result.exit_code == 0
    assert (
        "Updated git-backed pipeline (pipeline_id: pipeline-id) on branch 'main' at commit abc123"
        in result.output
    )


def test_update_git_backed_push_failure_can_retry_on_new_branch(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")
    suggested_branch = "orchestra-migrate-pipeline-ABC123"
    monkeypatch.setattr(
        git_module,
        "suggest_migration_branch_name",
        lambda: suggested_branch,
    )

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
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "update", "--path", str(yaml_file)],
        input="\n\n\n\n",
    )

    assert result.exit_code == 0
    assert "branch protection" in result.output
    assert suggested_branch in result.output
    assert (
        "Updated git-backed pipeline "
        f"(pipeline_id: pipeline-id) on branch '{suggested_branch}' at commit abc1234"
    ) in result.output


def test_update_success_without_pipeline_id_fails(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json={"alias": "demo"},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "success response did not include pipeline id" in result.output


def test_update_success_with_invalid_json_fails(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        text="ok",
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "update", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "success response was not valid JSON" in result.output
