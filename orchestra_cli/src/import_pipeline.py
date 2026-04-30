import json
import re
from pathlib import Path

import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_api_url
from ..utils.git import detect_repo_root, git_warnings, run_git_command
from ..utils.styling import bold, green, red, yellow
from ..utils.yaml_loader import load_validated_pipeline_data


def _detect_repository_url(repo_root: Path) -> str | None:
    ok, remote = run_git_command(["remote", "get-url", "origin"], repo_root)
    if not ok or not remote:
        return None

    # First, handle special cases like Azure URLs by removing segments like /_git/
    cleaned_remote = re.sub(r"/(?:_git|scm|v3)(?=/)", "", remote.strip())

    # A single regex can then capture the owner/repo from the cleaned URL
    pattern = r".*[:/]([^/]+)/([^/]+?)(?:\.git)?/?$"

    if match := re.search(pattern, cleaned_remote):
        return f"{match.group(1)}/{match.group(2)}"

    return None


def _get_remote_url(repo_root: Path) -> str | None:
    """Return the raw git remote URL for origin without transformation."""
    ok, remote = run_git_command(["remote", "get-url", "origin"], repo_root)
    if not ok:
        return None
    return remote


def _detect_default_branch(repo_root: Path) -> str | None:
    # Try symbolic-ref of remote HEAD first
    ok, out = run_git_command(["symbolic-ref", "refs/remotes/origin/HEAD"], repo_root)
    if ok and out:
        # refs/remotes/origin/main -> main
        return out.split("/")[-1]
    # Fallback to parsing `git remote show origin`
    ok, out = run_git_command(["remote", "show", "origin"], repo_root)
    if ok and out:
        m = re.search(r"HEAD branch:\s*(\S+)", out)
        if m:
            return m.group(1)
    return None


def _detect_current_branch(repo_root: Path) -> str | None:
    ok, out = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    if ok and out:
        return out
    return None


def _detect_storage_provider(repository_url: str | None) -> str:
    if not repository_url:
        typer.echo(red("Could not detect storage provider - no repository URL"))
        raise typer.Exit(code=1)
    url = repository_url.lower()
    if "github.com" in url:
        return "GITHUB"
    if "gitlab.com" in url:
        return "GITLAB"
    if any(host in url for host in ["dev.azure.com", "azure.com", "visualstudio.com"]):
        return "AZURE_DEVOPS"
    typer.echo(red("Could not detect storage provider - no matching host"))
    raise typer.Exit(code=1)


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
    working_branch: str | None = typer.Option(
        None,
        "--working-branch",
        "-w",
        help="Git branch to use for the imported pipeline (defaults to current local branch)",
    ),
):
    """
    Create a pipeline in Orchestra by referencing a YAML file in your git repository.
    """
    api_key = require_api_key()
    load_validated_pipeline_data(path)

    # Detect git repository info
    repo_root = detect_repo_root(path.parent)
    if repo_root is None:
        typer.echo(red("Not a git repository (could not detect repository root)"))
        raise typer.Exit(code=1)

    repository_slug = _detect_repository_url(repo_root)
    if not repository_slug:
        typer.echo(red("Could not detect repository URL from git"))
        raise typer.Exit(code=1)
    default_branch = _detect_default_branch(repo_root)
    if not default_branch:
        typer.echo(red("Could not detect default branch from git"))
        raise typer.Exit(code=1)

    # Determine working branch (explicit option or current branch)
    if working_branch is None:
        working_branch = _detect_current_branch(repo_root)
        if not working_branch:
            typer.echo(red("Could not detect current branch from git"))
            raise typer.Exit(code=1)

    # Compute YAML path relative to repo root
    try:
        yaml_path = str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        typer.echo(red("YAML file must be inside the git repository"))
        raise typer.Exit(code=1)

    for w in git_warnings(repo_root):
        typer.echo(yellow(f"⚠ {w}"))

    payload = {
        "storage_provider": _detect_storage_provider(_get_remote_url(repo_root)),
        "repository": repository_slug,
        "default_branch": default_branch,
        "working_branch": working_branch,
        "yaml_path": yaml_path,
        "alias": alias,
    }

    response = request_or_exit(
        httpx.post,
        get_api_url("import"),
        json=payload,
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 201:
        try:
            body = response.json()
        except Exception:
            body = {}
        pipeline_id = body.get("id")
        if pipeline_id:
            typer.echo(f"Pipeline with alias '{alias}' imported successfully: {pipeline_id}")
            raise typer.Exit(code=0)
        # Fallback if server does not return a field we expect
        typer.echo(green("✅ Pipeline imported successfully"))
        if body:
            typer.echo(bold(json.dumps(body)))
        raise typer.Exit(code=0)

    fail_with_response("Import", response)
