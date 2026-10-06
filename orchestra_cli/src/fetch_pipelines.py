import json

import typer

from ..utils.api import (
    account_id_option,
    api_client,
    fail_with_response,
    request_or_exit,
    require_credential,
)
from ..utils.constants import get_api_url
from ..utils.styling import indent_message, red, yellow


def fetch_pipelines(account_id: str | None = account_id_option()):
    """
    Fetch pipelines available to the current Orchestra API key.

    The API always includes each pipeline's latest run metadata.
    """
    require_credential()
    client = api_client(account_id)

    response = request_or_exit(
        client.get,
        get_api_url("pipelines"),
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

    raise fail_with_response("Fetch pipelines", response)
