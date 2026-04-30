"""Shared HTTP helpers for talking to the Orchestra API.

These helpers exist so that every command implementation handles auth, request
errors, and error-response rendering in the same way. Commands should never
construct ``Authorization`` headers, wrap ``httpx`` calls in ``try/except`` for
transport errors, or hand-roll JSON-vs-text error rendering themselves.
"""

import json
import os
from collections.abc import Callable

import httpx
import typer

from .styling import indent_message, red, yellow


def require_api_key() -> str:
    """Return ``ORCHESTRA_API_KEY`` from the environment or exit with code 1."""
    api_key = os.getenv("ORCHESTRA_API_KEY")
    if not api_key:
        typer.echo(red("ORCHESTRA_API_KEY is not set"))
        raise typer.Exit(code=1)
    return api_key


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


def fail_with_response(action: str, response: httpx.Response) -> None:
    """Echo a uniform ``❌ <action> failed with status <code>`` error and exit 1."""
    typer.echo(red(f"❌ {action} failed with status {response.status_code}"))
    echo_response_error_body(response)
    raise typer.Exit(code=1)
