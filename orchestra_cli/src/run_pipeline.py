import os
from pathlib import Path

import httpx
import typer

from ..utils.constants import API_URL
from ..utils.git import detect_repo_root, git_warnings
from ..utils.styling import bold, indent_message, red, yellow


def run_pipeline(
    alias: str = typer.Option(..., "--alias", "-a", help="Pipeline alias"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Git branch name"),
    commit: str | None = typer.Option(None, "--commit", "-c", help="Commit SHA"),
):
    """
    Run a pipeline in Orchestra.
    """
    api_key = os.getenv("ORCHESTRA_API_KEY")
    if not api_key:
        typer.echo(red("ORCHESTRA_API_KEY is not set"))
        raise typer.Exit(code=1)

    # Detect repo root (best-effort). If not a git repo, skip warnings.
    cwd = Path.cwd()
    repo_root = detect_repo_root(cwd)
    if repo_root is not None:
        warnings = git_warnings(repo_root)
        if warnings:
            for w in warnings:
                typer.echo(yellow(f"⚠ {w}"))
            typer.echo(bold(yellow("Press Enter to continue or Ctrl+C to abort")))
            try:
                input()
            except KeyboardInterrupt:
                typer.echo(red("Aborted"))
                raise typer.Exit(code=1)

    payload: dict[str, str] = {}
    if branch:
        payload["branch"] = branch
    if commit:
        payload["commit"] = commit

    try:
        response = httpx.post(
            API_URL.format(f"{alias}/start"),
            json=payload if payload else None,
            timeout=30,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if 200 <= response.status_code < 300:
        try:
            body = response.json()
        except Exception:
            body = {}
        typer.echo(
            f"Pipeline (alias: {alias}) run successfully started: {body.get('pipeline_run_id')}",
        )
        raise typer.Exit(code=0)

    typer.echo(red(f"❌ Run failed with status {response.status_code}"))
    try:
        typer.echo(
            yellow(
                indent_message(
                    (
                        response.text
                        if not response.headers.get("content-type", "").startswith(
                            "application/json",
                        )
                        else indent_message(response.json())
                    ),
                ),
            ),
        )
    except Exception:
        typer.echo(yellow(indent_message(response.text)))
    raise typer.Exit(code=1)
