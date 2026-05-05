from pathlib import Path

import httpx
import typer

from ..utils.api import auth_headers, fail_with_response, request_or_exit, require_api_key
from ..utils.constants import get_create_pipeline_url, get_update_pipeline_url
from ..utils.styling import green, indent_message, red, yellow
from ..utils.yaml_loader import load_validated_pipeline_data
from .pipeline_upsert import build_upsert_payload
from .run_pipeline import build_run_payload, confirm_warnings_or_exit, start_pipeline_run


def _extract_pipeline_version(response: httpx.Response, action: str) -> int:
    try:
        body = response.json()
    except Exception:
        typer.echo(red(f"❌ {action} failed: success response was not valid JSON"))
        typer.echo(yellow(indent_message(response.text)))
        raise typer.Exit(code=1)

    version_number = body.get("latestVersionNumber")
    if version_number is None:
        version_number = body.get("currentVersionNumber")
    if not isinstance(version_number, int):
        typer.echo(
            red(f"❌ {action} failed: success response did not include draft version number"),
        )
        raise typer.Exit(code=1)

    return version_number


def _upsert_draft_pipeline(alias: str, path: Path, api_key: str) -> int:
    data = load_validated_pipeline_data(path)
    payload = build_upsert_payload(data, publish=False)

    typer.echo(f"Creating or updating draft pipeline (alias: {alias})")
    update_response = request_or_exit(
        httpx.put,
        get_update_pipeline_url(alias),
        json=payload,
        timeout=30,
        headers=auth_headers(api_key),
    )

    if update_response.status_code == 200:
        version_number = _extract_pipeline_version(update_response, "Build")
        typer.echo(green(f"✅ Draft pipeline '{alias}' updated as version {version_number}"))
        return version_number

    if update_response.status_code != 404:
        fail_with_response("Build", update_response)

    create_response = request_or_exit(
        httpx.post,
        get_create_pipeline_url(),
        json={**payload, "alias": alias},
        timeout=30,
        headers=auth_headers(api_key),
    )

    if create_response.status_code == 201:
        version_number = _extract_pipeline_version(create_response, "Build")
        typer.echo(green(f"✅ Draft pipeline '{alias}' created as version {version_number}"))
        return version_number

    fail_with_response("Build", create_response)
    raise typer.Exit(code=1)


def build_pipeline(
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
        help="Path to pipeline YAML",
    ),
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
) -> None:
    """
    Validate local YAML, create or update a draft pipeline, and start the draft version.
    """
    api_key = require_api_key()
    confirm_warnings_or_exit(force)
    version_number = _upsert_draft_pipeline(alias, path, api_key)

    start_pipeline_run(
        alias=alias,
        api_key=api_key,
        payload=build_run_payload(branch=branch, commit=commit, version_number=version_number),
        wait=wait,
        failure_action="Build",
    )
