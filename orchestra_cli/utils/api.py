"""Shared HTTP helpers for talking to the Orchestra API.

These helpers exist so that every command implementation handles auth, request
errors, and error-response rendering in the same way. Commands should never
construct ``Authorization`` headers, wrap ``httpx`` calls in ``try/except`` for
transport errors, or hand-roll JSON-vs-text error rendering themselves.
"""

import json
import os
import time
from collections.abc import Callable
from typing import Any

import httpx
import typer

from .credentials import clear_credentials, load_credentials, save_credentials
from .styling import indent_message, red, yellow

# Refresh this long before expiry so a token cannot lapse mid-request.
_REFRESH_MARGIN_SECONDS = 60

# The workspace a multi-account login token acts in, stored by ``account_id_option()``.
_account_id: str | None = None


def _store_account_id(value: str | None) -> str | None:
    global _account_id
    _account_id = value
    return value


def account_id_option() -> Any:
    """Return the ``--account-id`` option, which ``auth_headers()`` picks up with no further wiring.

    Click runs the callback on every invocation, unset or not, so one command's
    account never leaks into the next.
    """
    return typer.Option(
        None,
        "--account-id",
        envvar="ORCHESTRA_ACCOUNT_ID",
        callback=_store_account_id,
        help="Workspace to act in, for a login that covers several accounts",
    )


def require_credential() -> str:
    """Return the bearer credential for API calls, or exit with code 1.

    An ``orchestra login`` session wins, refreshed first if it is about to expire;
    ``ORCHESTRA_API_KEY`` is the fallback for CI, scripts and anyone not logged in.
    """
    credentials = load_credentials()
    logged_in = credentials is not None
    if credentials and credentials["expires_at"] - _REFRESH_MARGIN_SECONDS <= time.time():
        credentials = _refresh(credentials)
    if credentials:
        return credentials["access_token"]
    api_key = os.getenv("ORCHESTRA_API_KEY")
    if api_key:
        if logged_in:
            # stderr, so output piped from a command that otherwise succeeds stays clean.
            typer.echo(
                yellow("Your Orchestra login has expired; using ORCHESTRA_API_KEY."),
                err=True,
            )
        return api_key
    if logged_in:
        typer.echo(red("Your Orchestra login has expired. Run `orchestra login` again."))
    else:
        typer.echo(red("You are not logged in and ORCHESTRA_API_KEY is not set"))
        typer.echo(yellow("Run `orchestra login`, or set ORCHESTRA_API_KEY."))
    raise typer.Exit(code=1)


def _refresh(credentials: dict) -> dict | None:
    """Return refreshed credentials, or ``None`` if the login is no longer usable.

    Refresh starts before expiry, so if the token endpoint is unreachable or erroring
    the current token still works: it is kept and the next call retries. Only a
    token that has actually lapsed makes that fatal.
    """
    try:
        response = httpx.post(
            credentials["token_endpoint"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": credentials["refresh_token"],
                "client_id": credentials["client_id"],
            },
            timeout=30,
        )
    except httpx.HTTPError as e:
        # Checked after the request, which can itself outlast the token.
        if credentials["expires_at"] > time.time():
            return credentials
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)
    if 400 <= response.status_code < 500:
        # Another CLI process may have refreshed first, rotating the refresh token
        # this one sent; its saved result is then still good. Otherwise the login
        # itself is unusable (invalid_grant, or a registration that has since expired)
        # and is forgotten, so later calls don't retry a refresh that cannot succeed.
        latest = load_credentials()
        if latest and latest["refresh_token"] != credentials["refresh_token"]:
            return latest
        clear_credentials()
        return None
    if response.status_code != 200:
        if credentials["expires_at"] > time.time():
            return credentials
        raise fail_with_response("Token refresh", response)
    refreshed = token_response_to_credentials(response.json(), credentials)
    save_credentials(refreshed)
    return refreshed


def token_response_to_credentials(token: dict, previous: dict) -> dict:
    """Merge a ``/token`` response over the previous credentials.

    Refresh tokens rotate, so every response carries a new one that replaces the old.
    """
    return {
        **previous,
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "expires_at": time.time() + token["expires_in"],
    }


def auth_headers(scoped: bool = True) -> dict[str, str]:
    """Return the ``Authorization`` header, plus ``X-Orchestra-Account-Id`` if set, for one request.

    The account is ``--account-id``, then ``ORCHESTRA_ACCOUNT_ID``, then the
    ``orchestra accounts use`` default; ``scoped=False`` leaves it out for calls that
    aren't about one workspace. Resolved afresh each time so a command running longer
    than an access token's lifetime keeps working; build headers per request rather
    than reusing them.
    """
    headers = {"Authorization": f"Bearer {require_credential()}"}
    # Read after require_credential(), which forgets a dead login before falling back
    # to ORCHESTRA_API_KEY, so a key never carries the login's default.
    account_id = (_account_id or (load_credentials() or {}).get("account_id")) if scoped else None
    if account_id:
        headers["X-Orchestra-Account-Id"] = account_id
    return headers


def request_or_exit(
    httpx_func: Callable[..., httpx.Response],
    *args: object,
    **kwargs: object,
) -> httpx.Response:
    """Invoke an ``httpx`` request function, exiting cleanly on transport errors.

    Takes the ``httpx`` callable (e.g. ``httpx.post``) rather than a method
    string so existing tests can still ``monkeypatch.setattr(httpx, "delete", ...)``
    to simulate transport failures.
    """
    try:
        return httpx_func(*args, **kwargs)
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)


def echo_response_error_body(response: httpx.Response) -> None:
    """Echo a response body as indented JSON if possible, falling back to text."""
    try:
        typer.echo(yellow(indent_message(json.dumps(response.json(), indent=2))))
        return
    except Exception:
        pass
    if response.text:
        typer.echo(yellow(indent_message(response.text)))


def fail_with_response(action: str, response: httpx.Response) -> typer.Exit:
    """Echo a uniform ``❌ <action> failed with status <code>`` error and exit 1."""
    typer.echo(red(f"❌ {action} failed with status {response.status_code}"))
    echo_response_error_body(response)
    # The API's message names a header, and it has no error code to match instead.
    if response.status_code == 400 and "covers several accounts" in _detail(response):
        typer.echo(
            yellow(
                "Pick one with --account-id, or set a default with `orchestra accounts use`"
                " (see `orchestra accounts list`).",
            ),
        )
    return typer.Exit(code=1)


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except Exception:
        return ""
    return detail if isinstance(detail, str) else ""
