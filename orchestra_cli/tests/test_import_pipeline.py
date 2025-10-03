from pathlib import Path
from typing import Any, Dict, Optional

import builtins
import types
from typer.testing import CliRunner

from orchestra_cli.src.cli import app


runner = CliRunner()


class FakeResponse:
    def __init__(self, status_code: int, json_data: Optional[Dict[str, Any]] = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("No JSON")
        return self._json


def make_git_subprocess_mock(mapping: dict[tuple[str, ...], tuple[int, str, str]]):
    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _mock_run(args, cwd=None, capture_output=False, text=False, check=False):
        # args begins with ["git", ...]
        key = tuple(args[1:])
        rc, out, err = mapping.get(key, (1, "", ""))
        return Result(rc, out, err)

    return _mock_run


def test_import_success(monkeypatch, tmp_path: Path):
    # Arrange repo with YAML inside
    repo_root = tmp_path
    yaml_file = repo_root / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    # Mock httpx.post: first schema 200, then import 201
    calls: list[str] = []

    def fake_post(url: str, json: dict, timeout: int):  # type: ignore[override]
        calls.append(url)
        if url.endswith("/schema"):
            return FakeResponse(200, {"ok": True})
        if url.endswith("/import"):
            return FakeResponse(201, {"pipeline_id": "abc-123"})
        return FakeResponse(404, {"detail": "not found"})

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)

    # Mock git
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("status", "--porcelain"): (0, "", ""),
        # Do not provide upstream to skip that branch check path
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }

    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    # Act
    result = runner.invoke(app, ["import-pipeline", "--alias", "demo", "--path", str(yaml_file)])

    # Assert
    assert result.exit_code == 0
    # Should print only the pipeline id
    assert result.output.strip() == "abc-123"
    # Ensure both endpoints were called
    assert any(u.endswith("/schema") for u in calls)
    assert any(u.endswith("/import") for u in calls)


def test_import_invalid_yaml(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [oops\n")
    result = runner.invoke(app, ["import-pipeline", "--alias", "demo", "--path", str(bad)])
    assert result.exit_code == 1
    assert "Invalid YAML" in result.output


def test_import_schema_validation_error(monkeypatch, tmp_path: Path):
    good = tmp_path / "ok.yaml"
    good.write_text("name: ok\n")

    def fake_post(url: str, json: dict, timeout: int):  # type: ignore[override]
        if url.endswith("/schema"):
            return FakeResponse(400, {"detail": [{"loc": ["root"], "msg": "bad"}]})
        return FakeResponse(500, {"detail": "should not be called"})

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)

    result = runner.invoke(app, ["import-pipeline", "--alias", "demo", "--path", str(good)])
    assert result.exit_code == 1
    assert "Validation failed" in result.output


def test_import_api_error(monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    yaml_file = repo_root / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    def fake_post(url: str, json: dict, timeout: int):  # type: ignore[override]
        if url.endswith("/schema"):
            return FakeResponse(200, {"ok": True})
        if url.endswith("/import"):
            return FakeResponse(400, {"detail": "bad"})
        return FakeResponse(404)

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }

    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(app, ["import-pipeline", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "Import failed" in result.output


def test_not_a_git_repo(monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text("name: ok\n")

    def fake_post(url: str, json: dict, timeout: int):  # type: ignore[override]
        if url.endswith("/schema"):
            return FakeResponse(200, {"ok": True})
        return FakeResponse(500)

    import httpx
    import subprocess

    monkeypatch.setattr(httpx, "post", fake_post)
    # rev-parse --show-toplevel fails
    mapping = {
        ("rev-parse", "--show-toplevel"): (1, "", "fatal: not a git repo"),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(app, ["import-pipeline", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "Not a git repository" in result.output


def test_missing_repo_or_branch(monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    f = repo_root / "p.yaml"
    f.write_text("name: ok\n")

    def fake_post(url: str, json: dict, timeout: int):  # type: ignore[override]
        if url.endswith("/schema"):
            return FakeResponse(200, {"ok": True})
        return FakeResponse(500)

    import httpx
    import subprocess

    monkeypatch.setattr(httpx, "post", fake_post)

    # repo root ok, but cannot get remote url or default branch
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("remote", "get-url", "origin"): (1, "", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (1, "", ""),
        ("remote", "show", "origin"): (0, "", ""),
        ("status", "--porcelain"): (0, "", ""),
    }
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(app, ["import-pipeline", "--alias", "demo", "--path", str(f)])
    assert result.exit_code == 1
    assert "Could not detect repository URL or default branch" in result.output


def test_warnings_printed(monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    f = repo_root / "p.yaml"
    f.write_text("name: ok\n")

    def fake_post(url: str, json: dict, timeout: int):  # type: ignore[override]
        if url.endswith("/schema"):
            return FakeResponse(200, {"ok": True})
        if url.endswith("/import"):
            return FakeResponse(201, {"pipeline_id": "xyz"})
        return FakeResponse(500)

    import httpx
    import subprocess

    monkeypatch.setattr(httpx, "post", fake_post)

    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("symbolic-ref", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main", ""),
        ("status", "--porcelain"): (0, " M p.yaml\n", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-parse", "HEAD"): (0, "aaaa", ""),
        ("rev-parse", "@{u}"): (0, "bbbb", ""),
        ("status", "-sb"): (0, "## main...origin/main [behind 1]", ""),
    }

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    result = runner.invoke(app, ["import-pipeline", "--alias", "demo", "--path", str(f)])
    assert result.exit_code == 0
    assert "⚠ Uncommitted changes" in result.output
    assert "Local branch SHA does not match remote branch SHA" in result.output
    assert "not on latest HEAD of the branch" in result.output
