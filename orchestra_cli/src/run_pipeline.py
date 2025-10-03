import os
from pathlib import Path

import httpx
import typer

from ..utils.constants import API_URL
from ..utils.git import _detect_repo_root, _git_warnings
from ..utils.styling import bold, green, indent_message, red, yellow


def run_pipeline(
    alias: str = typer.Option(..., "--alias", "-a", help="Pipeline alias"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Git branch name"),
    commit: str | None = typer.Option(None, "--commit", "-c", help="Commit SHA"),
):
    """
    Run a pipeline in Orchestra.
    """
    api_key = os.getenv("ORCHESTRA_API_KEY")

    # Detect repo root (best-effort). If not a git repo, skip warnings.
    cwd = Path.cwd()
    repo_root = _detect_repo_root(cwd)
    if repo_root is not None:
        warnings = _git_warnings(repo_root)
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
        request_kwargs = {}
        if api_key:
            request_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
        response = httpx.post(
            API_URL.format(f"{alias}/start"),
            json=payload if payload else None,
            timeout=30,
            **request_kwargs,
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if 200 <= response.status_code < 300:
        try:
            body = response.json()
        except Exception:
            body = {}
        exec_id = body.get("execution_id") or body.get("run_id") or body.get("id")
        if exec_id:
            typer.echo(str(exec_id))
            raise typer.Exit(code=0)
        else:
            typer.echo(green("✅ Run started"))
            if body:
                typer.echo(bold(str(body)))
            raise typer.Exit(code=0)

    typer.echo(red(f"❌ Run failed with status {response.status_code}"))
    try:
        typer.echo(yellow(indent_message(response.text if not response.headers.get("content-type", "").startswith("application/json") else indent_message(response.json()))))
    except Exception:
        typer.echo(yellow(indent_message(response.text)))
    raise typer.Exit(code=1)
