import subprocess
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app
from tests.conftest import make_git_subprocess_mock

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")
    monkeypatch.setenv("BASE_URL", "")


def test_migrate_success_uses_default_branch_without_working_branch(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "pipelines" / "demo.yaml"

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 3,
            "latestVersionNumber": 3,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=3",
        text="name: remote\nversion: 1\n",
        status_code=200,
    )
    httpx_mock.add_response(
        method="PATCH",
        url="https://app.getorchestra.io/api/engine/public/pipelines/storage-settings?alias=demo",
        json={"ok": True},
        status_code=200,
        match_json={
            "path": "pipelines/demo.yaml",
            "repository": "org/repo",
            "storage_provider": "GITHUB",
            "default_branch": "main",
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("status", "--porcelain", "--", "pipelines/demo.yaml"): (0, "?? pipelines/demo.yaml", ""),
        ("add", "--", "pipelines/demo.yaml"): (0, "", ""),
        ("commit", "-m", "Migrate pipeline 'demo' to git-backed storage"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
        ("push", "-u", "origin", "main"): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
    )

    assert result.exit_code == 0
    assert "migrated pipeline" in result.output.lower()
    assert "compare link" not in result.output.lower()
    assert target_file.read_text() == "name: remote\nversion: 1\n"


def test_migrate_prompts_for_latest_version_and_prints_compare_link(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "pipelines" / "demo.yaml"

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 2,
            "latestVersionNumber": 5,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=5",
        text="name: remote\n",
        status_code=200,
    )
    httpx_mock.add_response(
        method="PATCH",
        url="https://app.getorchestra.io/api/engine/public/pipelines/storage-settings?alias=demo",
        json={"ok": True},
        status_code=200,
        match_json={
            "path": "pipelines/demo.yaml",
            "repository": "org/repo",
            "storage_provider": "GITHUB",
            "default_branch": "main",
            "working_branch": "feature/migrate",
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "feature/migrate", ""),
        ("status", "--porcelain", "--", "pipelines/demo.yaml"): (0, "?? pipelines/demo.yaml", ""),
        ("add", "--", "pipelines/demo.yaml"): (0, "", ""),
        ("commit", "-m", "Migrate pipeline 'demo' to git-backed storage"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
            0,
            "origin/feature/migrate",
            "",
        ),
        ("push",): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
        input="\n",
    )

    assert result.exit_code == 0
    assert "Select 1 or 2" in result.output
    assert "Open PR / compare link" in result.output
    assert "github.com/org/repo/compare/main...feature/migrate" in result.output


def test_migrate_uses_local_file_when_conflict_choice_is_local(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "pipelines" / "demo.yaml"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("name: local\n")

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 1,
            "latestVersionNumber": 1,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=1",
        text="name: remote\n",
        status_code=200,
    )
    httpx_mock.add_response(
        method="PATCH",
        url="https://app.getorchestra.io/api/engine/public/pipelines/storage-settings?alias=demo",
        json={"ok": True},
        status_code=200,
        match_json={
            "path": "pipelines/demo.yaml",
            "repository": "org/repo",
            "storage_provider": "GITHUB",
            "default_branch": "main",
            "working_branch": "feature/local",
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "feature/local", ""),
        ("status", "--porcelain", "--", "pipelines/demo.yaml"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
            0,
            "origin/feature/local",
            "",
        ),
        ("push",): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
        input="2\n",
    )

    assert result.exit_code == 0
    assert "Local file differs from Orchestra YAML" in result.output
    assert target_file.read_text() == "name: local\n"


def test_migrate_fails_when_pipeline_is_already_git_backed(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "pipelines" / "demo.yaml"

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "feature/migrate", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
    )

    assert result.exit_code == 1
    assert "already git-backed" in result.output


def test_migrate_branch_protection_offer_retries_with_suggested_branch(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "pipelines" / "demo.yaml"
    suggested_branch = "orchestra-migrate-pipeline-ABC123"
    monkeypatch.setattr(
        "orchestra_cli.src.migrate_pipeline.suggest_migration_branch_name",
        lambda: suggested_branch,
    )

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 1,
            "latestVersionNumber": 1,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=1",
        text="name: remote\n",
        status_code=200,
    )
    httpx_mock.add_response(
        method="PATCH",
        url="https://app.getorchestra.io/api/engine/public/pipelines/storage-settings?alias=demo",
        json={"ok": True},
        status_code=200,
        match_json={
            "path": "pipelines/demo.yaml",
            "repository": "org/repo",
            "storage_provider": "GITHUB",
            "default_branch": "main",
            "working_branch": suggested_branch,
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("status", "--porcelain", "--", "pipelines/demo.yaml"): (0, "?? pipelines/demo.yaml", ""),
        ("add", "--", "pipelines/demo.yaml"): (0, "", ""),
        ("commit", "-m", "Migrate pipeline 'demo' to git-backed storage"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("push",): (1, "", "remote: push blocked by branch protection"),
        ("checkout", "-b", suggested_branch): (0, "", ""),
        ("branch", "-f", "main", "HEAD~1"): (0, "", ""),
        ("push", "-u", "origin", suggested_branch): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
        input="\n",
    )

    assert result.exit_code == 0
    assert "branch protection" in result.output.lower()
    assert suggested_branch in result.output


def test_migrate_accepts_nonexistent_parent_directory_inside_repo(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "new-subdir" / "demo.yaml"

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 1,
            "latestVersionNumber": 1,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=1",
        text="name: remote\n",
        status_code=200,
    )
    httpx_mock.add_response(
        method="PATCH",
        url="https://app.getorchestra.io/api/engine/public/pipelines/storage-settings?alias=demo",
        json={"ok": True},
        status_code=200,
        match_json={
            "path": "new-subdir/demo.yaml",
            "repository": "org/repo",
            "storage_provider": "GITHUB",
            "default_branch": "main",
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("status", "--porcelain", "--", "new-subdir/demo.yaml"): (0, "?? new-subdir/demo.yaml", ""),
        ("add", "--", "new-subdir/demo.yaml"): (0, "", ""),
        ("commit", "-m", "Migrate pipeline 'demo' to git-backed storage"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
        ("push", "-u", "origin", "main"): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
    )

    assert result.exit_code == 0
    assert target_file.read_text() == "name: remote\n"


def test_migrate_force_skips_version_prompt(monkeypatch, tmp_path: Path, httpx_mock: HTTPXMock):
    target_file = tmp_path / "pipelines" / "demo.yaml"

    def fail_input() -> str:
        raise AssertionError("input should not be called when --force is set")

    monkeypatch.setattr("builtins.input", fail_input)

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 1,
            "latestVersionNumber": 2,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=2",
        text="name: remote\n",
        status_code=200,
    )
    httpx_mock.add_response(
        method="PATCH",
        url="https://app.getorchestra.io/api/engine/public/pipelines/storage-settings?alias=demo",
        json={"ok": True},
        status_code=200,
        match_json={
            "path": "pipelines/demo.yaml",
            "repository": "org/repo",
            "storage_provider": "GITHUB",
            "default_branch": "main",
            "working_branch": "feature/force",
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "feature/force", ""),
        ("status", "--porcelain", "--", "pipelines/demo.yaml"): (0, "?? pipelines/demo.yaml", ""),
        ("add", "--", "pipelines/demo.yaml"): (0, "", ""),
        ("commit", "-m", "Migrate pipeline 'demo' to git-backed storage"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
        ("push", "-u", "origin", "feature/force"): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file), "--force"],
    )

    assert result.exit_code == 0
    assert "--force selected latest version" in result.output


def test_migrate_force_skips_branch_recovery_prompt(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "pipelines" / "demo.yaml"
    suggested_branch = "orchestra-migrate-pipeline-FORCE1"
    monkeypatch.setattr(
        "orchestra_cli.src.migrate_pipeline.suggest_migration_branch_name",
        lambda: suggested_branch,
    )

    def fail_input() -> str:
        raise AssertionError("input should not be called when --force is set")

    monkeypatch.setattr("builtins.input", fail_input)

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 1,
            "latestVersionNumber": 1,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=1",
        text="name: remote\n",
        status_code=200,
    )
    httpx_mock.add_response(
        method="PATCH",
        url="https://app.getorchestra.io/api/engine/public/pipelines/storage-settings?alias=demo",
        json={"ok": True},
        status_code=200,
        match_json={
            "path": "pipelines/demo.yaml",
            "repository": "org/repo",
            "storage_provider": "GITHUB",
            "default_branch": "main",
            "working_branch": suggested_branch,
        },
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("status", "--porcelain", "--", "pipelines/demo.yaml"): (0, "?? pipelines/demo.yaml", ""),
        ("add", "--", "pipelines/demo.yaml"): (0, "", ""),
        ("commit", "-m", "Migrate pipeline 'demo' to git-backed storage"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("push",): (1, "", "remote: push blocked by branch protection"),
        ("checkout", "-b", suggested_branch): (0, "", ""),
        ("branch", "-f", "main", "HEAD~1"): (0, "", ""),
        ("push", "-u", "origin", suggested_branch): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file), "--force"],
    )

    assert result.exit_code == 0
    assert "--force set; retrying push on suggested branch" in result.output


def test_migrate_fails_before_writing_when_reprompted_path_is_outside_repo(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    target_file = tmp_path / "pipelines" / "demo.yaml"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("name: local\n")
    outside_file = tmp_path.parent / "outside-repo" / "demo.yaml"

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipeline-id",
            "alias": "demo",
            "storage_provider": "ORCHESTRA",
            "publishedVersionNumber": 1,
            "latestVersionNumber": 1,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo&version=1",
        text="name: remote\n",
        status_code=200,
    )

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
        input=f"3\n{outside_file}\n",
    )

    assert result.exit_code == 1
    assert "YAML file must be inside the git repository" in result.output
    assert not outside_file.exists()


def test_migrate_fails_before_git_write_when_storage_provider_is_unsupported(
    monkeypatch,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    del httpx_mock
    target_file = tmp_path / "pipelines" / "demo.yaml"

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@gitea.example.com:org/repo.git", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(
        app,
        ["pipeline", "migrate", "--alias", "demo", "--path", str(target_file)],
    )

    assert result.exit_code == 1
    assert "Could not detect storage provider - no matching host" in result.output
    assert not target_file.exists()
