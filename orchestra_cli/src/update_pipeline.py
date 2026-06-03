from pathlib import Path

import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_update_pipeline_url
from ..utils.git import GitAction, prepare_git_backed_run_target
from ..utils.pipeline_lookup import lookup_existing_pipeline
from ..utils.pipeline_selector import (
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.pipeline_update import build_update_selector, storage_provider
from ..utils.styling import green, red
from ..utils.yaml_loader import load_validated_pipeline_data
from .pipeline_upsert import (
    build_upsert_payload,
    emit_success_with_edit_url,
    require_pipeline_id_from_success_response,
)


def update_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
    publish: bool = typer.Option(
        False,
        "--publish/--no-publish",
        help="Whether the pipeline is published and can be triggered",
    ),
    force: bool = typer.Option(
        False,
        "--force/--no-force",
        help="Ignore prompts and continue with inferred git update choices",
    ),
):
    """
    Update an Orchestra-backed pipeline from a local YAML file.
    """
    api_key = require_api_key()
    if path is None:
        typer.echo(red("Provide --path to update a pipeline from YAML"))
        raise typer.Exit(code=1)
    selector = resolve_pipeline_selector(alias, pipeline_id, path, force=force)
    data = load_validated_pipeline_data(path)
    existing_pipeline = lookup_existing_pipeline(selector, api_key, "Update")
    if existing_pipeline is None:
        typer.echo(red("❌ Update failed: pipeline lookup returned no pipeline"))
        raise typer.Exit(code=1)
    pipeline_storage_provider = (storage_provider(existing_pipeline) or "ORCHESTRA").upper()

    if pipeline_storage_provider != "ORCHESTRA":
        update_selector = build_update_selector(existing_pipeline, "Update")
        git_branch, git_commit = prepare_git_backed_run_target(
            path=path,
            existing_pipeline=existing_pipeline,
            force=force,
            action=GitAction.UPDATE,
        )
        typer.echo(
            green(
                "✅ Updated git-backed pipeline "
                f"({update_selector.display()}) on branch '{git_branch}' at commit {git_commit}",
            ),
        )
        raise typer.Exit(code=0)

    update_selector = build_update_selector(existing_pipeline, "Update")
    payload = build_upsert_payload(data, publish, update_selector)

    response = request_or_exit(
        httpx.put,
        get_update_pipeline_url(),
        json=payload,
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 200:
        pipeline_id = require_pipeline_id_from_success_response(response, "Update")
        emit_success_with_edit_url(update_selector.display(), "updated", pipeline_id)
        raise typer.Exit(code=0)

    raise fail_with_response("Update", response)
