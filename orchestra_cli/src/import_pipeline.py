from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

import httpx
import typer
import yaml

from ..utils.constants import API_URL
from ..utils.styling import bold, green, indent_message, red, yellow


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


def _detect_repo_root(start_path: Path) -> Optional[Path]:
    ok, out = _run_git_command(["rev-parse", "--show-toplevel"], start_path)
    if not ok:
        return None
    return Path(out)


def _detect_repository_url(repo_root: Path) -> Optional[str]:
    ok, out = _run_git_command(["remote", "get-url", "origin"], repo_root)
    if not ok:
        return None
    return out


def _detect_default_branch(repo_root: Path) -> Optional[str]:
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


def _detect_storage_provider(repository_url: Optional[str]) -> str:
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


def _git_warnings(repo_root: Path) -> list[str]:
    warnings: list[str] = []
    # Uncommitted changes
    ok, out = _run_git_command(["status", "--porcelain"], repo_root)
    if ok and out:
        warnings.append("Uncommitted changes detected in repository")

    # Not on latest commit of the branch / local vs remote mismatch
    # Try to compare local HEAD to upstream if it exists
    ok, branch = _run_git_command(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], repo_root)
    if ok and branch:
        ok_head, head = _run_git_command(["rev-parse", "HEAD"], repo_root)
        ok_up, upstream = _run_git_command(["rev-parse", "@{u}"], repo_root)
        if ok_head and ok_up and head and upstream and head != upstream:
            warnings.append("Local branch SHA does not match remote branch SHA")
            # If behind, call out explicitly
            ok_stat, stat = _run_git_command(["status", "-sb"], repo_root)
            if ok_stat and "behind" in stat:
                warnings.append("You are not on latest HEAD of the branch (behind remote)")
    return warnings


def _load_yaml(file: Path) -> tuple[Optional[dict], Optional[str]]:
    try:
        with file.open("r") as f:
            data = yaml.safe_load(f)
        return data, None
    except Exception as e:
        return None, str(e)


def _validate_yaml_with_api(data: dict) -> tuple[bool, Optional[str]]:
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
        ..., "--path", "-p", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True,
        help="Path to pipeline YAML inside a git repository",
    ),
):
    """
    Create a pipeline in Orchestra by referencing a YAML file in your git repository.
    """
    if not path.exists():
        typer.echo(red(f"File not found: {path}"))
        raise typer.Exit(code=1)

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
    repo_root = _detect_repo_root(path.parent)
    if repo_root is None:
        typer.echo(red("Not a git repository (could not detect repository root)"))
        raise typer.Exit(code=1)

    repository_url = _detect_repository_url(repo_root)
    default_branch = _detect_default_branch(repo_root)
    if repository_url is None or default_branch is None:
        typer.echo(red("Could not detect repository URL or default branch from git"))
        raise typer.Exit(code=1)

    # Compute YAML path relative to repo root
    try:
        yaml_path = str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        typer.echo(red("YAML file must be inside the git repository"))
        raise typer.Exit(code=1)

    # Show warnings (no interactive confirmation per instructions)
    for w in _git_warnings(repo_root):
        typer.echo(yellow(f"⚠ {w}"))
    typer.echo(yellow("TODO: Prompt user to press Enter to continue when warnings are present."))

    storage_provider = _detect_storage_provider(repository_url)

    payload = {
        "storage_provider": storage_provider,
        "repository": repository_url,
        "default_branch": default_branch,
        "yaml_path": yaml_path,
    }

    try:
        response = httpx.post(API_URL.format("import"), json=payload, timeout=20)
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
