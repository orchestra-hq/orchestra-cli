import json
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
from ..utils.git import (
    detect_current_branch,
    detect_default_branch,
    detect_repo_root,
    detect_repository_slug,
    detect_storage_provider,
    get_remote_url,
    git_warnings,
)
from ..utils.pipeline_selector import pipeline_alias_option, pipeline_path_option
from ..utils.styling import bold, green, red, yellow
from ..utils.yaml_loader import load_validated_pipeline_data


def import_pipeline(
    path: Path | None = pipeline_path_option("Path to pipeline YAML inside a git repository"),
    alias: str | None = pipeline_alias_option(),
    default_branch: str | None = typer.Option(
        None,
        "--default-branch",
        help="Default branch for the imported pipeline (defaults to the git remote default branch)",
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
    if path is None:
        typer.echo(red("Provide --path to import a pipeline from git"))
        raise typer.Exit(code=1)
    load_validated_pipeline_data(path)

    # Detect git repository info
    repo_root = detect_repo_root(path.parent)
    if repo_root is None:
        typer.echo(red("Not a git repository (could not detect repository root)"))
        raise typer.Exit(code=1)

    repository_slug = detect_repository_slug(repo_root)
    if not repository_slug:
        typer.echo(red("Could not detect repository URL from git"))
        raise typer.Exit(code=1)
    if not default_branch:
        default_branch = detect_default_branch(repo_root)
        if not default_branch:
            typer.echo(red("Could not detect default branch from git"))
            raise typer.Exit(code=1)

    # Determine working branch (explicit option or current branch)
    if working_branch is None:
        working_branch = detect_current_branch(repo_root, allow_detached=False)
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

    storage_provider = detect_storage_provider(get_remote_url(repo_root))
    if not storage_provider:
        typer.echo(red("Could not detect storage provider - no matching host"))
        raise typer.Exit(code=1)

    payload = {
        "storage_provider": storage_provider,
        "repository": repository_slug,
        "default_branch": default_branch,
        "working_branch": working_branch,
        "yaml_path": yaml_path,
    }
    if alias:
        payload["alias"] = alias

    response = request_or_exit(
        httpx.post,
        get_api_url("pipelines/import"),
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
            identifier = f"alias '{alias}'" if alias else f"{repository_slug}/{yaml_path}"
            typer.echo(f"Pipeline with {identifier} imported successfully: {pipeline_id}")
            raise typer.Exit(code=0)
        # Fallback if server does not return a field we expect
        typer.echo(green("✅ Pipeline imported successfully"))
        if body:
            typer.echo(bold(json.dumps(body)))
        raise typer.Exit(code=0)

    raise fail_with_response("Import", response)
