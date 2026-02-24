import os
import time
from pathlib import Path

import httpx
import typer

from ..utils.constants import get_api_url
from ..utils.git import detect_repo_root, git_warnings
from ..utils.styling import bold, green, indent_message, red, yellow


def run_pipeline(
    alias: str = typer.Option(..., "--alias", "-a", help="Pipeline alias"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Git branch name"),
    commit: str | None = typer.Option(None, "--commit", "-c", help="Commit SHA"),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll the pipeline run until it completes",
    ),
    force: bool = typer.Option(
        False,
        "--force/--no-force",
        help="Ignore any warnings and run the pipeline anyway",
    ),
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
            if not force:
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
        typer.echo(f"Starting pipeline (alias: {alias})")
        response = httpx.post(
            get_api_url(f"{alias}/start"),
            json=payload if payload else None,
            timeout=30,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if 200 <= response.status_code < 300:
        # Extract pipeline run id from response body using several possible keys
        try:
            body = response.json()
        except Exception:
            body = {}

        pipeline_run_id = body.get("pipelineRunId")

        if not pipeline_run_id:
            typer.echo(
                yellow(
                    f"Started pipeline (alias: {alias}), "
                    "but could not determine run id from response",
                ),
            )
            raise typer.Exit(code=0)

        # If not waiting, print only the id (to preserve existing behavior/tests)
        if not wait:
            typer.echo(f"Started pipeline (alias: {alias}), run id: {str(pipeline_run_id)}")
            raise typer.Exit(code=0)

        # Derive base API and host for status + lineage URLs
        api_prefix = get_api_url(f"{alias}/start").split("/pipelines/")[
            0
        ]  # https://dev.getorchestra.io/api/engine/public
        host = get_api_url(f"{alias}/start").split("/api/")[0]  # https://dev.getorchestra.io

        lineage_url = f"{host}/pipeline-runs/{pipeline_run_id}/lineage"

        typer.echo(green(f"Started pipeline (alias: {alias}), run id: {pipeline_run_id}"))
        typer.echo(yellow(f"Lineage: {lineage_url}"))
        typer.echo(bold("Polling pipeline status... (Ctrl+C to stop)"))

        # Poll until we hit a terminal state
        poll_interval_seconds = 5
        headers = {"Authorization": f"Bearer {api_key}"}
        status_url = f"{api_prefix}/pipeline_runs/{pipeline_run_id}/status"
        in_progress_statuses = {"RUNNING", "QUEUED", "CREATED"}

        while True:
            time.sleep(poll_interval_seconds)
            try:
                status_resp = httpx.get(status_url, headers=headers, timeout=30)
            except Exception as e:
                typer.echo(yellow(f"Polling request failed: {e}"))
                continue

            if not (200 <= status_resp.status_code < 300):
                typer.echo(red(f"❌ Status check failed with HTTP {status_resp.status_code}"))
                try:
                    typer.echo(yellow(indent_message(status_resp.text)))
                except Exception:
                    pass
                raise typer.Exit(code=1)

            try:
                status_body = status_resp.json()
            except Exception:
                status_body = {}

            status_value = status_body.get("runStatus")

            if status_value:
                typer.echo(f"Pipeline ({alias}) status: {status_value}")

            if status_value == "SUCCEEDED":
                typer.echo(green("✅ Pipeline succeeded"))
                # Print the run id at the end for easy scripting/grepping
                typer.echo(str(pipeline_run_id))
                raise typer.Exit(code=0)

            if status_value == "WARNING":
                typer.echo(yellow("⚠ Pipeline completed with warnings"))
                typer.echo(str(pipeline_run_id))
                raise typer.Exit(code=0)

            if status_value == "SKIPPED":
                typer.echo(yellow("⚠ Pipeline skipped"))
                typer.echo(str(pipeline_run_id))
                raise typer.Exit(code=0)

            if status_value in {"FAILED", "CANCELLED"}:
                typer.echo(
                    red(
                        f"❌ Pipeline ended with status {status_value}. See lineage for details.",
                    ),
                )
                typer.echo(yellow(lineage_url))
                raise typer.Exit(code=1)

            if status_value in in_progress_statuses:
                continue

            typer.echo(
                red(f"❌ Invalid status value: {status_value}\nResponse body: {status_body}"),
            )

    typer.echo(red(f"❌ Run failed with status code {response.status_code}"))
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
