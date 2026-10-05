import httpx
import typer

from .api import auth_headers, fail_with_response, request_or_exit
from .constants import get_api_url
from .styling import indent_message, red, yellow


def fetch_accounts() -> list[dict]:
    """Return the workspaces the current credential covers as ``[{id, name}]``, or exit 1.

    Sent without an account header: the call isn't scoped to one workspace, so a
    stale default account must not break it.
    """
    response = request_or_exit(
        httpx.get,
        get_api_url("accounts"),
        timeout=30,
        headers=auth_headers(scoped=False),
    )
    if response.status_code != 200:
        raise fail_with_response("List accounts", response)
    try:
        return response.json()
    except Exception:
        typer.echo(red("❌ List accounts failed: success response was not valid JSON"))
        typer.echo(yellow(indent_message(response.text)))
        raise typer.Exit(code=1)
