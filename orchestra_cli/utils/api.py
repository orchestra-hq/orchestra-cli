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

import httpx
import typer

from .credentials import load_credentials, save_credentials
from .styling import indent_message, red, yellow

# Refresh this long before expiry so a token cannot lapse mid-request.
_REFRESH_MARGIN_SECONDS = 60


def require_api_key() -> str:
    """Return the bearer credential for API calls, or exit with code 1.

    ``ORCHESTRA_API_KEY`` wins when set, so CI and scripts behave exactly as before
    ``orchestra login`` existed. Otherwise the cached login token is used, refreshed
    first if it is about to expire.
    """
    api_key = os.getenv("ORCHESTRA_API_KEY")
    if api_key:
        return api_key
    credentials = load_credentials()
    if not credentials:
        typer.echo(red("ORCHESTRA_API_KEY is not set and you are not logged in"))
        typer.echo(yellow("Run `orchestra login`, or set ORCHESTRA_API_KEY."))
        raise typer.Exit(code=1)
    if credentials["expires_at"] - _REFRESH_MARGIN_SECONDS <= time.time():
        credentials = _refresh(credentials)
    return credentials["access_token"]


def _refresh(credentials: dict) -> dict:
    response = request_or_exit(
        httpx.post,
        credentials["token_endpoint"],
        data={
            "grant_type": "refresh_token",
            "refresh_token": credentials["refresh_token"],
            "client_id": credentials["client_id"],
        },
        timeout=30,
    )
    if 400 <= response.status_code < 500:
        # Another CLI process may have refreshed first, rotating the refresh token
        # this one sent; its saved result is then still good.
        latest = load_credentials()
        if latest and latest["refresh_token"] != credentials["refresh_token"]:
            return latest
        # Otherwise the login itself is unusable (invalid_grant, or a registration
        # that has since expired) and only a fresh one fixes it.
        typer.echo(red("Your Orchestra login has expired. Run `orchestra login` again."))
        echo_response_error_body(response)
        raise typer.Exit(code=1)
    if response.status_code != 200:
        raise fail_with_response("Token refresh", response)
    refreshed = token_response_to_credentials(response.json(), credentials)
    save_credentials(refreshed)
    return refreshed


def token_response_to_credentials(token: dict, previous: dict) -> dict:
    """Merge a ``/token`` response over the previous credentials.

    Refresh tokens rotate, so the response's one replaces the old; if the server
    ever omits it, the old one is kept rather than lost.
    """
    return {
        **previous,
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token", previous.get("refresh_token")),
        "expires_at": time.time() + token["expires_in"],
    }


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


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
    return typer.Exit(code=1)
