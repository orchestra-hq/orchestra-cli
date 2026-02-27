import json
import os
from pathlib import Path

import httpx
import typer

from ..utils.constants import get_create_pipeline_url
from ..utils.styling import green, indent_message, red, yellow
from .import_pipeline import _load_yaml, _validate_yaml_with_api


def create_pipeline(
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
    Create an Orchestra-backed pipeline from a local YAML file.
    """
    if not path.exists():
        typer.echo(red(f"File not found: {path}"))
        raise typer.Exit(code=1)

    api_key = os.getenv("ORCHESTRA_API_KEY")
    if not api_key:
        typer.echo(red("ORCHESTRA_API_KEY is not set"))
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

    payload = {
        "alias": alias,
        "data": data or {},
        "published": publish,
        "storage_provider": "ORCHESTRA",
    }

    try:
        response = httpx.post(
            get_create_pipeline_url(),
            json=payload,
            timeout=30,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if response.status_code == 201:
        try:
            body = response.json()
        except Exception:
            body = {}
        pipeline_id = body.get("id")
        if pipeline_id:
            typer.echo(green(f"✅ Pipeline '{alias}' created successfully: {pipeline_id}"))
        else:
            typer.echo(green(f"✅ Pipeline '{alias}' created successfully"))
        raise typer.Exit(code=0)

    typer.echo(red(f"❌ Create failed with status {response.status_code}"))
    try:
        typer.echo(yellow(indent_message(json.dumps(response.json(), indent=2))))
    except Exception:
        typer.echo(yellow(indent_message(response.text)))
    raise typer.Exit(code=1)
