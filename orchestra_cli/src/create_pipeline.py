from pathlib import Path

import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_create_pipeline_url
from ..utils.pipeline_selector import (
    pipeline_alias_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.styling import red
from ..utils.yaml_loader import load_validated_pipeline_data
from .pipeline_upsert import (
    build_upsert_payload,
    emit_success_with_edit_url,
    require_pipeline_id_from_success_response,
)


def create_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    publish: bool = typer.Option(
        False,
        "--publish/--no-publish",
        help="Whether the pipeline is published and can be triggered",
    ),
):
    """
    Create an Orchestra-backed pipeline from a local YAML file.
    """
    api_key = require_api_key()
    if path is None:
        typer.echo(red("Provide --path to create a pipeline from YAML"))
        raise typer.Exit(code=1)
    selector = resolve_pipeline_selector(
        alias,
        path=path,
        allow_pipeline_id=False,
        use_git_path_selector=False,
    )
    data = load_validated_pipeline_data(path)
    payload = build_upsert_payload(data, publish, selector)

    response = request_or_exit(
        httpx.post,
        get_create_pipeline_url(),
        json=payload,
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 201:
        pipeline_id = require_pipeline_id_from_success_response(response, "Create")
        emit_success_with_edit_url(selector.display(), "created", pipeline_id)
        raise typer.Exit(code=0)

    fail_with_response("Create", response)
