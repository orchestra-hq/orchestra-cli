import typer

from ..utils.accounts import fetch_accounts
from ..utils.credentials import load_credentials, save_credentials
from ..utils.picker import can_pick, pick
from ..utils.styling import green, red, yellow


def use_account(
    id_or_name: str | None = typer.Argument(
        None,
        help="Workspace id, or its name (case-insensitive). Omit it to pick from a list.",
    ),
):
    """Set the workspace later commands act in when no --account-id is given."""
    _require_login()
    if id_or_name is None and not can_pick():
        typer.echo(red("No terminal to pick an account in; pass a workspace id or name."))
        raise typer.Exit(code=1)
    accounts = fetch_accounts()
    account = _pick(accounts) if id_or_name is None else _match(accounts, id_or_name)
    # Read again after fetching, which may have refreshed and rotated the saved tokens.
    credentials = _require_login()
    save_credentials({**credentials, "account_id": account["id"], "account_name": account["name"]})
    typer.echo(green(f"Default account: {account['name']}"))


def _match(accounts: list[dict], id_or_name: str) -> dict:
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
    return matches[0]


def _pick(accounts: list[dict]) -> dict:
    if not accounts:
        typer.echo(red("Your login covers no accounts."))
        raise typer.Exit(code=1)
    default_id = (load_credentials() or {}).get("account_id")
    start = next((i for i, account in enumerate(accounts) if account["id"] == default_id), 0)
    # The id tells apart workspaces that share a name.
    index = pick([f"{account['name']} ({account['id']})" for account in accounts], start)
    if index is None:
        typer.echo(yellow("Cancelled; the default account is unchanged."))
        raise typer.Exit(code=1)
    return accounts[index]


def _require_login() -> dict:
    credentials = load_credentials()
    if credentials is None:
        typer.echo(red("A default account needs `orchestra login`; an API key covers one account."))
        raise typer.Exit(code=1)
    return credentials
