from pathlib import Path

import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_pipeline_url, get_update_pipeline_url
from ..utils.git import prepare_git_backed_run_target
from ..utils.pipeline_selector import (
    PipelineSelector,
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.styling import green, red
from ..utils.yaml_loader import load_validated_pipeline_data
from .pipeline_upsert import (
    build_upsert_payload,
    emit_success_with_edit_url,
    require_pipeline_body_from_success_response,
    require_pipeline_id_from_success_response,
)


def _lookup_existing_pipeline(
    selector: PipelineSelector,
    api_key: str,
) -> dict[str, object]:
    response = request_or_exit(
        httpx.get,
        get_pipeline_url(),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code != 200:
        raise fail_with_response("Update", response)

    return require_pipeline_body_from_success_response(response, "Update")


def _build_update_selector(existing_pipeline: dict[str, object]) -> PipelineSelector:
    pipeline_id = existing_pipeline.get("id") or existing_pipeline.get("pipeline_id")
    if pipeline_id:
        return PipelineSelector(pipeline_id=str(pipeline_id))

    alias = existing_pipeline.get("alias")
    if alias:
        return PipelineSelector(alias=str(alias))

    typer.echo(
        red("❌ Update failed: existing pipeline metadata did not include alias or pipeline id"),
    )
    raise typer.Exit(code=1)


def _storage_provider(existing_pipeline: dict[str, object]) -> str | None:
    for key in ("storage_provider", "storageProvider"):
        value = existing_pipeline.get(key)
        if isinstance(value, str):
            return value
    return None


def update_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
    publish: bool = typer.Option(
        False,
        "--publish/--no-publish",
        help="Whether the pipeline is published and can be triggered",
    ),
):
    """
    Update an Orchestra-backed pipeline from a local YAML file.
    """
    api_key = require_api_key()
    if path is None:
        typer.echo(red("Provide --path to update a pipeline from YAML"))
        raise typer.Exit(code=1)
    selector = resolve_pipeline_selector(alias, pipeline_id, path)
    data = load_validated_pipeline_data(path)
    existing_pipeline = _lookup_existing_pipeline(selector, api_key)
    storage_provider = (_storage_provider(existing_pipeline) or "ORCHESTRA").upper()

    if storage_provider != "ORCHESTRA":
        update_selector = _build_update_selector(existing_pipeline)
        git_branch, git_commit = prepare_git_backed_run_target(
            path=path,
            existing_pipeline=existing_pipeline,
            force=False,
        )
        typer.echo(
            green(
                "✅ Updated git-backed pipeline "
                f"({update_selector.display()}) on branch '{git_branch}' at commit {git_commit}",
            ),
        )
        raise typer.Exit(code=0)

    update_selector = _build_update_selector(existing_pipeline)
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
