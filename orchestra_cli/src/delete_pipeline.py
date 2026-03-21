import json

import httpx
import typer

from ..utils.constants import get_delete_pipeline_url
from ..utils.styling import indent_message, green, red, yellow
from .pipeline_upsert import require_api_key


def delete_pipeline(
    alias: str = typer.Option(..., "--alias", "-a", help="Pipeline alias"),
):
    """
    Delete a pipeline by alias.
    """
    api_key = require_api_key()

    try:
        response = httpx.delete(
            get_delete_pipeline_url(alias),
            timeout=30,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if response.status_code == 204:
        typer.echo(green(f"✅ Pipeline '{alias}' deleted successfully"))
        raise typer.Exit(code=0)

    typer.echo(red(f"❌ Delete failed with status {response.status_code}"))
    try:
        typer.echo(yellow(indent_message(json.dumps(response.json(), indent=2))))
    except Exception:
        if response.text:
            typer.echo(yellow(indent_message(response.text)))
    raise typer.Exit(code=1)
