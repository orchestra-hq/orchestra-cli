import json

import httpx
import typer

from ..utils.constants import get_api_url
from ..utils.styling import indent_message, red, yellow
from .pipeline_upsert import require_api_key


def fetch_pipelines(
    fetch_latest_run_data: bool = typer.Option(
        True,
        "--fetch-latest-run-data/--no-fetch-latest-run-data",
        help="Whether to include each pipeline's latest run metadata",
    ),
):
    """
    Fetch pipelines available to the current Orchestra API key.
    """
    api_key = require_api_key()
    params = None
    if not fetch_latest_run_data:
        params = {"fetch_latest_run_data": "false"}

    try:
        response = httpx.get(
            get_api_url(""),
            params=params,
            timeout=30,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if response.status_code == 200:
        try:
            pipelines = response.json()
        except Exception:
            typer.echo(red("❌ Fetch pipelines failed: success response was not valid JSON"))
            typer.echo(yellow(indent_message(response.text)))
            raise typer.Exit(code=1)

        typer.echo(json.dumps(pipelines, indent=2))
        raise typer.Exit(code=0)

    typer.echo(red(f"❌ Fetch pipelines failed with status {response.status_code}"))
    try:
        typer.echo(yellow(indent_message(json.dumps(response.json(), indent=2))))
    except Exception:
        typer.echo(yellow(indent_message(response.text)))
    raise typer.Exit(code=1)
