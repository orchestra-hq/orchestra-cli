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
from ..utils.constants import get_api_url, get_pipeline_url
from ..utils.pipeline_selector import (
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.styling import indent_message, red, yellow


def get_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
):
    """
    Fetch one pipeline using the shared selector model.
    """
    api_key = require_api_key()
    selector = resolve_pipeline_selector(alias, pipeline_id, path)

    response = request_or_exit(
        httpx.get,
        get_pipeline_url(),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 200:
        try:
            pipeline = response.json()
        except Exception:
            typer.echo(red("❌ Get pipeline failed: success response was not valid JSON"))
            typer.echo(yellow(indent_message(response.text)))
            raise typer.Exit(code=1)

        typer.echo(json.dumps(pipeline, indent=2))
        raise typer.Exit(code=0)

    fail_with_response("Get pipeline", response)


def fetch_pipelines():
    """
    Fetch pipelines available to the current Orchestra API key.

    The API always includes each pipeline's latest run metadata.
    """
    api_key = require_api_key()

    response = request_or_exit(
        httpx.get,
        get_api_url("pipelines"),
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 200:
        try:
            pipelines = response.json()
        except Exception:
            typer.echo(red("❌ Fetch pipelines failed: success response was not valid JSON"))
            typer.echo(yellow(indent_message(response.text)))
            raise typer.Exit(code=1)

        typer.echo(json.dumps(pipelines, indent=2))
        raise typer.Exit(code=0)

    fail_with_response("Fetch pipelines", response)
