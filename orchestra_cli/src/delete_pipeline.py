import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_delete_pipeline_url
from ..utils.styling import green


def delete_pipeline(
    alias: str = typer.Option(..., "--alias", "-a", help="Pipeline alias"),
):
    """
    Delete a pipeline by alias.
    """
    api_key = require_api_key()

    response = request_or_exit(
        httpx.delete,
        get_delete_pipeline_url(alias),
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 204:
        typer.echo(green(f"✅ Pipeline '{alias}' deleted successfully"))
        raise typer.Exit(code=0)

    fail_with_response("Delete", response)
