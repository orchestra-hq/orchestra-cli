from pathlib import Path

import pytest

from orchestra_cli.utils import git as git_module
from tests.conftest import make_git_subprocess_mock


def test_prepare_git_backed_run_target_happy_path_clean_repo(monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("status", "--porcelain", "--", "pipe.yaml"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-list", "--left-right", "--count", "@{u}...HEAD"): (0, "0 0", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("rev-parse", "HEAD"): (0, "abc123", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    branch, commit = git_module.prepare_git_backed_run_target(
        yaml_file,
        {"alias": "demo"},
        False,
    )
    assert branch == "main"
    assert commit == "abc123"


def test_prepare_git_backed_run_target_commits_and_pushes_dirty_yaml(monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("status", "--porcelain", "--", "pipe.yaml"): (0, " M pipe.yaml", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-list", "--left-right", "--count", "@{u}...HEAD"): (0, "0 0", ""),
        ("add", "--", "pipe.yaml"): (0, "", ""),
        ("commit", "-m", "Migrating pipeline: 'demo'"): (0, "[main abc123] commit", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("push",): (0, "", ""),
        ("rev-parse", "HEAD"): (0, "def456", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    branch, commit = git_module.prepare_git_backed_run_target(
        yaml_file,
        {"alias": "demo"},
        True,
    )
    assert branch == "main"
    assert commit == "def456"


def test_suggest_migration_branch_name_format(monkeypatch):
    def fake_choices(_chars: str, k: int) -> list[str]:
        assert k == 6
        return list("ABC123")

    monkeypatch.setattr(git_module.random, "choices", fake_choices)
    assert git_module.suggest_migration_branch_name() == "orchestra-migrate-pipeline-ABC123"


def test_stage_and_commit_file_if_needed_no_changes(monkeypatch, tmp_path: Path):
    mapping = {
        ("status", "--porcelain", "--", "pipe.yaml"): (0, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    git_module.stage_and_commit_file_if_needed(
        repo_root=tmp_path,
        relative_path="pipe.yaml",
        commit_message="test commit",
        action=git_module.GitAction.MIGRATE,
    )


def test_stage_and_commit_file_if_needed_commit_failure_raises(monkeypatch, tmp_path: Path):
    mapping = {
        ("status", "--porcelain", "--", "pipe.yaml"): (0, " M pipe.yaml", ""),
        ("add", "--", "pipe.yaml"): (0, "", ""),
        ("commit", "-m", "test commit"): (1, "", "fatal: commit failed"),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    with pytest.raises(git_module.typer.Exit):
        git_module.stage_and_commit_file_if_needed(
            repo_root=tmp_path,
            relative_path="pipe.yaml",
            commit_message="test commit",
            action=git_module.GitAction.MIGRATE,
        )


def test_require_repo_root_walks_up_from_nonexistent_parent(monkeypatch, tmp_path: Path):
    target_file = tmp_path / "new-subdir" / "pipe.yaml"

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    assert git_module.require_repo_root(target_file, git_module.GitAction.MIGRATE) == tmp_path


@pytest.mark.parametrize(
    "remote_url, expected",
    [
        ("https://github.com/org/repo.git", "GITHUB"),
        ("git@github.com:org/repo.git", "GITHUB"),
        ("https://acme.ghe.com/org/repo.git", "GITHUB"),
        ("https://user:token@acme.ghe.com/org/repo.git", "GITHUB"),
        ("git@acme.ghe.com:org/repo.git", "GITHUB"),
        ("ssh://git@acme.ghe.com/org/repo.git", "GITHUB"),
        ("https://gitlab.com/org/repo.git", "GITLAB"),
        ("https://git.example.com/org/repo.git", None),
        ("https://example.com/ghe.com/repo.git", None),
        (None, None),
    ],
)
def test_detect_storage_provider(remote_url: str | None, expected: str | None):
    assert git_module.detect_storage_provider(remote_url) == expected


@pytest.mark.parametrize(
    "remote_url, expected",
    [
        (
            "git@github.com:org/repo.git",
            "https://github.com/org/repo/compare/main...feature?expand=1",
        ),
        (
            "git@acme.ghe.com:org/repo.git",
            "https://acme.ghe.com/org/repo/compare/main...feature?expand=1",
        ),
        (
            "https://user:token@acme.ghe.com/org/repo.git",
            "https://acme.ghe.com/org/repo/compare/main...feature?expand=1",
        ),
        (None, "https://github.com/org/repo/compare/main...feature?expand=1"),
    ],
)
def test_build_compare_link_github(remote_url: str | None, expected: str):
    link = git_module.build_compare_link("GITHUB", "org/repo", "main", "feature", remote_url)
    assert link == expected
