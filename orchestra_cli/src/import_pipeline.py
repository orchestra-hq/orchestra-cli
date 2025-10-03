from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import httpx
import typer
import yaml

from ..utils.constants import API_URL
from ..utils.styling import bold, green, indent_message, red, yellow
from ..utils.git import _detect_repo_root, _git_warnings


def _run_git_command(args: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except Exception as e:
        return False, str(e)


def _detect_repo_root_local(start_path: Path) -> Path | None:
    return _detect_repo_root(start_path)


def _detect_repository_url(repo_root: Path) -> str | None:
    ok, remote = _run_git_command(["remote", "get-url", "origin"], repo_root)
    if not ok or not remote:
        return None

    # Normalize and extract an owner/repo-style slug from a variety of git URL formats
    url = remote.strip()

    # Remove protocol scheme if present (e.g., https://, ssh://, git://)
    if "://" in url:
        url = url.split("://", 1)[1]
        # Remove leading auth part like git@ if present after scheme
        if "@" in url and url.index("@") < url.index("/"):
            url = url.split("@", 1)[1]

    # Convert scp-like syntax git@host:owner/repo.git to host/owner/repo.git
    if ":" in url and ("/" not in url.split(":", 1)[0]):
        host, path_part = url.split(":", 1)
        url = f"{host}/{path_part}"

    # Drop hostname, keep path
    path = url
    if "/" in url:
        path = url.split("/", 1)[1]

    # Split path, remove empty and service-specific segments
    segments = [seg for seg in path.split("/") if seg]
    # Remove common service-specific segments
    filtered = [seg for seg in segments if seg not in {"_git", "scm", "v3"}]

    if not filtered:
        return None

    # Remove trailing .git from last segment
    filtered[-1] = filtered[-1][:-4] if filtered[-1].endswith(".git") else filtered[-1]

    # Prefer last two path components as slug (owner/repo)
    if len(filtered) >= 2:
        owner, repo = filtered[-2], filtered[-1]
        return f"{owner}/{repo}"

    # Fallback: if only one component remains, return it (unlikely)
    return filtered[-1]


def _get_remote_url(repo_root: Path) -> str | None:
    """Return the raw git remote URL for origin without transformation."""
    ok, remote = _run_git_command(["remote", "get-url", "origin"], repo_root)
    if not ok:
        return None
    return remote


def _detect_default_branch(repo_root: Path) -> str | None:
    # Try symbolic-ref of remote HEAD first
    ok, out = _run_git_command(["symbolic-ref", "refs/remotes/origin/HEAD"], repo_root)
    if ok and out:
        # refs/remotes/origin/main -> main
        return out.split("/")[-1]
    # Fallback to parsing `git remote show origin`
    ok, out = _run_git_command(["remote", "show", "origin"], repo_root)
    if ok and out:
        m = re.search(r"HEAD branch:\s*(\S+)", out)
        if m:
            return m.group(1)
    return None


def _detect_storage_provider(repository_url: str | None) -> str:
    if not repository_url:
        return "ORCHESTRA"
    url = repository_url.lower()
    if any(host in url for host in ["github.com", ":github.com"]):
        return "GITHUB"
    if any(host in url for host in ["gitlab.com", ":gitlab.com"]):
        return "GITLAB"
    if any(host in url for host in ["dev.azure.com", "azure.com", "visualstudio.com"]):
        return "AZURE_DEVOPS"
    if any(host in url for host in ["bitbucket.org", ":bitbucket.org"]):
        return "BITBUCKET"
    return "ORCHESTRA"


def _git_warnings_local(repo_root: Path) -> list[str]:
    return _git_warnings(repo_root)


def _load_yaml(file: Path) -> tuple[dict | None, str | None]:
    try:
        with file.open("r") as f:
            data = yaml.safe_load(f)
        return data, None
    except Exception as e:
        return None, str(e)


def _validate_yaml_with_api(data: dict) -> tuple[bool, str | None]:
    try:
        response = httpx.post(API_URL.format("schema"), json=data, timeout=15)
    except Exception as e:
        return False, f"HTTP request failed: {e}"

    if response.status_code == 200:
        return True, None
    try:
        errors = response.json()
        return False, json.dumps(errors, indent=2)
    except Exception:
        return False, response.text


def import_pipeline(
    alias: str = typer.Option(..., "--alias", "-a", help="Pipeline alias"),
    path: Path = typer.Option(
        ...,
        "--path",
        "-p",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Path to pipeline YAML inside a git repository",
    ),
):
    """
    Create a pipeline in Orchestra by referencing a YAML file in your git repository.
    """

    if not path.exists():
        typer.echo(red(f"File not found: {path}"))
        raise typer.Exit(code=1)

    api_key = os.getenv("ORCHESTRA_API_KEY")

    # Load and validate YAML with API first
    data, err = _load_yaml(path)
    if err is not None:
        typer.echo(red(f"Invalid YAML: {err}"))
        raise typer.Exit(code=1)

    ok, err_msg = _validate_yaml_with_api(data or {})
    if not ok:
        typer.echo(red("❌ Validation failed"))
        if err_msg:
            typer.echo(yellow(indent_message(err_msg)))
        raise typer.Exit(code=1)

    # Detect git repository info
    repo_root = _detect_repo_root_local(path.parent)
    if repo_root is None:
        typer.echo(red("Not a git repository (could not detect repository root)"))
        raise typer.Exit(code=1)

    repository_slug = _detect_repository_url(repo_root)
    default_branch = _detect_default_branch(repo_root)
    if repository_slug is None or default_branch is None:
        typer.echo(red("Could not detect repository URL or default branch from git"))
        raise typer.Exit(code=1)

    # Compute YAML path relative to repo root
    try:
        yaml_path = str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        typer.echo(red("YAML file must be inside the git repository"))
        raise typer.Exit(code=1)

    # Show warnings (skip interactive confirmation as a TODO per instructions)
    for w in _git_warnings_local(repo_root):
        typer.echo(yellow(f"⚠ {w}"))

    # Use the raw remote URL to detect storage provider reliably
    raw_remote = _get_remote_url(repo_root)
    storage_provider = _detect_storage_provider(raw_remote)

    payload = {
        "storage_provider": storage_provider,
        "repository": repository_slug,
        "default_branch": default_branch,
        "yaml_path": yaml_path,
        "alias": alias,
    }

    try:
        request_kwargs = {}
        if api_key:
            request_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
        response = httpx.post(
            API_URL.format("import"),
            json=payload,
            timeout=30,
            **request_kwargs,
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if response.status_code == 201:
        try:
            body = response.json()
        except Exception:
            body = {}
        pipeline_id = body.get("pipeline_id") or body.get("id")
        if pipeline_id:
            # Print only the pipeline id as requested
            typer.echo(str(pipeline_id))
            raise typer.Exit(code=0)
        else:
            # Fallback if server does not return a field we expect
            typer.echo(green("✅ Pipeline imported successfully"))
            if body:
                typer.echo(bold(json.dumps(body)))
            raise typer.Exit(code=0)

    # Error handling for non-201 responses
    typer.echo(red(f"❌ Import failed with status {response.status_code}"))
    try:
        typer.echo(yellow(indent_message(json.dumps(response.json(), indent=2))))
    except Exception:
        typer.echo(yellow(indent_message(response.text)))
    raise typer.Exit(code=1)
