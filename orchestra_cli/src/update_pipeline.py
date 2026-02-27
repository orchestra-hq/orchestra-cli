import json
from pathlib import Path

import httpx
import typer

from ..utils.constants import get_update_pipeline_url
from ..utils.styling import indent_message, red, yellow
from .pipeline_upsert import (
    build_upsert_payload,
    emit_success_with_edit_url,
    load_validated_pipeline_data,
    require_api_key,
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

    try:
        response = httpx.put(
            get_update_pipeline_url(alias),
            json=payload,
            timeout=30,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if response.status_code == 200:
        pipeline_id = require_pipeline_id_from_success_response(response, "Update")
        emit_success_with_edit_url(alias, "updated", pipeline_id)
        raise typer.Exit(code=0)

    typer.echo(red(f"❌ Update failed with status {response.status_code}"))
    try:
        typer.echo(yellow(indent_message(json.dumps(response.json(), indent=2))))
    except Exception:
        typer.echo(yellow(indent_message(response.text)))
    raise typer.Exit(code=1)
