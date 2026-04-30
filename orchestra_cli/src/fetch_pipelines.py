import json

import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_api_url
from ..utils.styling import indent_message, red, yellow


def fetch_pipelines():
    """
    Fetch pipelines available to the current Orchestra API key.

    The API always includes each pipeline's latest run metadata.
    """
    api_key = require_api_key()

    response = request_or_exit(
        httpx.get,
        get_api_url(""),
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
