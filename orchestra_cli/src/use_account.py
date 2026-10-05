import typer

from ..utils.accounts import fetch_accounts
from ..utils.credentials import load_credentials, save_credentials
from ..utils.styling import green, red, yellow


def use_account(
    id_or_name: str = typer.Argument(..., help="Workspace id, or its name (case-insensitive)"),
):
    """Set the workspace later commands act in when no --account-id is given."""
    accounts = fetch_accounts()
    matches = [account for account in accounts if account["id"] == id_or_name] or [
        account for account in accounts if account["name"].casefold() == id_or_name.casefold()
    ]
    if not matches:
        typer.echo(red(f"No account matches {id_or_name!r}."))
        typer.echo(yellow("Valid names: " + ", ".join(account["name"] for account in accounts)))
        raise typer.Exit(code=1)
    if len(matches) > 1:
        typer.echo(red(f"Several accounts are named {id_or_name!r}; pass the id instead."))
        for account in matches:
            typer.echo(yellow(f"  {account['id']}"))
        raise typer.Exit(code=1)

    # Read after fetching, which may have refreshed and rotated the saved tokens.
    credentials = load_credentials()
    if credentials is None:
        typer.echo(red("A default account needs `orchestra login`; an API key covers one account."))
        raise typer.Exit(code=1)
    account = matches[0]
    save_credentials({**credentials, "account_id": account["id"], "account_name": account["name"]})
    typer.echo(green(f"Default account: {account['name']}"))
