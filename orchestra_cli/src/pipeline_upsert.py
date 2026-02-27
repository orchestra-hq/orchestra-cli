import json
import os
from pathlib import Path

import httpx
import typer

from ..utils.constants import get_pipeline_edit_url
from ..utils.styling import green, indent_message, red, yellow
from .import_pipeline import _load_yaml, _validate_yaml_with_api


def require_api_key() -> str:
    api_key = os.getenv("ORCHESTRA_API_KEY")
    if not api_key:
        typer.echo(red("ORCHESTRA_API_KEY is not set"))
        raise typer.Exit(code=1)
    return api_key


def load_validated_pipeline_data(path: Path) -> dict:
    if not path.exists():
        typer.echo(red(f"File not found: {path}"))
        raise typer.Exit(code=1)

    data, err = _load_yaml(path)
    if err is not None:
        typer.echo(red(f"Invalid YAML: {err}"))
        raise typer.Exit(code=1)

    ok, err_msg = _validate_yaml_with_api(data or {})
    if not ok:
        typer.echo(red("❌ Validation failed"))
        if err_msg:
            typer.echo(yellow(indent_message(err_msg)))
        raise typer.Exit(code=1)

    return data or {}


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
