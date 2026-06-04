import json

import httpx
import typer

from .api import auth_headers, fail_with_response, request_or_exit
from .constants import get_api_url
from .pipeline_selector import PipelineSelector
from .styling import indent_message, red, yellow


def require_pipeline_lookup_body(
    response: httpx.Response,
    action: str,
) -> dict[str, object]:
    try:
        body = response.json()
    except Exception as exc:
        typer.echo(red(f"❌ {action} failed: pipeline lookup response was not valid JSON ({exc})"))
        typer.echo(yellow(indent_message(response.text)))
        raise typer.Exit(code=1)

    if not isinstance(body, dict):
        typer.echo(red(f"❌ {action} failed: pipeline lookup response was not a JSON object"))
        typer.echo(yellow(indent_message(json.dumps(body, indent=2))))
        raise typer.Exit(code=1)

    if not body:
        typer.echo(red(f"❌ {action} failed: pipeline lookup response was empty"))
        raise typer.Exit(code=1)

    return body


def lookup_existing_pipeline(
    selector: PipelineSelector,
    api_key: str,
    action: str,
    *,
    allow_404: bool = False,
) -> dict[str, object] | None:
    response = request_or_exit(
        httpx.get,
        get_api_url("pipeline"),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )
    if response.status_code == 404 and allow_404:
        return None
    if response.status_code != 200:
        raise fail_with_response(action, response)
    return require_pipeline_lookup_body(response, action)
