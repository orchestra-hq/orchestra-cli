import json

import typer

from ..utils.accounts import fetch_accounts


def list_accounts():
    """List the Orchestra workspaces the current login or API key covers."""
    typer.echo(json.dumps(fetch_accounts(), indent=2))
