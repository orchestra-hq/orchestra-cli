import json

import typer

from ..utils.accounts import fetch_accounts
from ..utils.credentials import load_credentials


def list_accounts():
    """List the Orchestra workspaces the current login or API key covers."""
    default_id = (load_credentials() or {}).get("account_id")
    accounts = [{**account, "default": account["id"] == default_id} for account in fetch_accounts()]
    typer.echo(json.dumps(accounts, indent=2))
