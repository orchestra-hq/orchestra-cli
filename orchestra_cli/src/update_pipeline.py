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
from ..utils.yaml_loader import load_validated_pipeline_data
from .pipeline_upsert import (
    build_upsert_payload,
    emit_success_with_edit_url,
    require_pipeline_id_from_success_response,
)


def update_pipeline(
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
    data = load_validated_pipeline_data(path)
    payload = build_upsert_payload(data, publish)

    response = request_or_exit(
        httpx.put,
        get_update_pipeline_url(alias),
        json=payload,
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 200:
        pipeline_id = require_pipeline_id_from_success_response(response, "Update")
        emit_success_with_edit_url(alias, "updated", pipeline_id)
        raise typer.Exit(code=0)

    fail_with_response("Update", response)
