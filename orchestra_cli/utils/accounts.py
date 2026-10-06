import httpx
import typer

from .api import auth_headers, fail_with_response, request_or_exit
from .constants import get_base_url
from .picker import pick
from .styling import indent_message, red, yellow


def fetch_accounts() -> list[dict]:
    """Return the workspaces the current credential covers as ``[{id, name}]``, or exit 1.

    Sent without an account header: the call isn't scoped to one workspace, so a
    stale default account must not break it.
    """
    response = request_or_exit(
        httpx.get,
        # Unlike the pipeline endpoints, this one is served from the public v1 API.
        f"{get_base_url()}/public/v1/accounts",
        timeout=30,
        headers=auth_headers(scoped=False),
    )
    if response.status_code != 200:
        raise fail_with_response("List accounts", response)
    try:
        accounts = response.json()
    except Exception:
        accounts = None
    if not isinstance(accounts, list) or not all(
        isinstance(account, dict) and "id" in account and "name" in account for account in accounts
    ):
        typer.echo(red("❌ List accounts failed: success response was not a list of accounts"))
        typer.echo(yellow(indent_message(response.text)))
        raise typer.Exit(code=1)
    return accounts


def pick_account(accounts: list[dict], default_id: str | None = None) -> dict | None:
    """Let the user choose one of ``accounts`` (not empty) in the picker; None if they cancel.

    The cursor starts on ``default_id`` when it is among them. Callers check ``can_pick()`` first.
    """
    start = next((i for i, account in enumerate(accounts) if account["id"] == default_id), 0)
    # The id tells apart workspaces that share a name.
    index = pick([f"{account['name']} ({account['id']})" for account in accounts], start)
    return None if index is None else accounts[index]
