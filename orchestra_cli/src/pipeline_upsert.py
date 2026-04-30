"""Helpers shared between ``create_pipeline`` and ``update_pipeline``.

Both commands share the same payload shape, success-response handling, and
post-success edit-URL output, so those bits live here. Anything not specific
to upsert (API key resolution, YAML loading) lives in ``orchestra_cli.utils``.
"""

import json

import httpx
import typer

from ..utils.constants import get_pipeline_edit_url
from ..utils.styling import green, indent_message, red, yellow


def build_upsert_payload(data: dict, publish: bool, alias: str | None = None) -> dict:
    payload: dict[str, object] = {
        "data": data,
        "published": publish,
        "storage_provider": "ORCHESTRA",
    }
    if alias is not None:
        payload["alias"] = alias
    return payload


def require_pipeline_id_from_success_response(
    response: httpx.Response,
    action: str,
) -> str:
    try:
        body = response.json()
    except Exception:
        typer.echo(red(f"❌ {action} failed: success response was not valid JSON"))
        typer.echo(yellow(indent_message(response.text)))
        raise typer.Exit(code=1)

    pipeline_id = body.get("id")
    if not pipeline_id:
        typer.echo(red(f"❌ {action} failed: success response did not include pipeline id"))
        typer.echo(yellow(indent_message(json.dumps(body, indent=2))))
        raise typer.Exit(code=1)

    return str(pipeline_id)


def emit_success_with_edit_url(alias: str, action: str, pipeline_id: str) -> None:
    typer.echo(green(f"✅ Pipeline '{alias}' {action} successfully: {pipeline_id}"))
    typer.echo(yellow(f"Edit URL: {get_pipeline_edit_url(pipeline_id)}"))
