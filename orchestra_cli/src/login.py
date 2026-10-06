import base64
import hashlib
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import typer

from ..utils.accounts import fetch_accounts, pick_account
from ..utils.api import fail_with_response, request_or_exit, token_response_to_credentials
from ..utils.constants import get_base_url
from ..utils.credentials import load_credentials, save_credentials
from ..utils.picker import can_pick
from ..utils.styling import green, red, yellow

SCOPES = "orchestra:read orchestra:write offline_access"
CALLBACK_PATH = "/callback"
LOGIN_TIMEOUT_SECONDS = 300


class _CallbackHandler(BaseHTTPRequestHandler):
    params: dict[str, str] | None = None
    # Bounds reads on connections a browser opens speculatively and never uses, which
    # would otherwise block the single-threaded server past the login deadline.
    timeout = 5

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        _CallbackHandler.params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(files(__package__).joinpath("login_page.html").read_bytes())

    def log_message(self, format, *args):  # noqa: ARG002
        pass


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _wait_for_callback(server: HTTPServer, state: str) -> dict[str, str]:
    """Wait for the redirect carrying this login's ``state``.

    Any other request to the callback (a prefetch, a stale tab, another local
    process) is ignored rather than ending the login.
    """
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    server.timeout = 1
    while True:
        _CallbackHandler.params = None
        if time.monotonic() > deadline:
            typer.echo(red("Timed out waiting for the browser to complete login"))
            raise typer.Exit(code=1)
        server.handle_request()
        params = _CallbackHandler.params
        if params is not None and params.get("state") == state:
            return params


def login():
    """
    Log in to Orchestra in your browser and cache the token for later commands.
    """
    base_url = get_base_url()
    response = request_or_exit(
        httpx.get,
        f"{base_url}/.well-known/oauth-authorization-server",
        timeout=30,
    )
    if response.status_code != 200:
        raise fail_with_response("Discovery", response)
    # The web app answers unknown paths with a 200 HTML page, so a host without an
    # authorization server behind it still reaches this point.
    try:
        metadata = response.json()
    except ValueError:
        metadata = None
    required = ("authorization_endpoint", "token_endpoint", "registration_endpoint")
    if not isinstance(metadata, dict) or not all(k in metadata for k in required):
        typer.echo(red(f"{base_url} does not support `orchestra login`"))
        raise typer.Exit(code=1)

    with HTTPServer(("127.0.0.1", 0), _CallbackHandler) as server:
        redirect_uri = f"http://127.0.0.1:{server.server_port}{CALLBACK_PATH}"

        response = request_or_exit(
            httpx.post,
            metadata["registration_endpoint"],
            json={
                "client_name": "Orchestra CLI",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            timeout=30,
        )
        if response.status_code not in (200, 201):
            raise fail_with_response("Client registration", response)
        client_id = response.json()["client_id"]

        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(32)
        authorize_url = f"{metadata['authorization_endpoint']}?" + urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )

        typer.echo(yellow("Opening your browser to log in. If it does not open, visit:"))
        typer.echo(authorize_url)
        webbrowser.open(authorize_url)
        params = _wait_for_callback(server, state)

    if "error" in params:
        detail = params.get("error_description", params["error"])
        typer.echo(red(f"Login failed: {detail}"))
        raise typer.Exit(code=1)

    response = request_or_exit(
        httpx.post,
        metadata["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": params.get("code", ""),
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise fail_with_response("Token exchange", response)
    token = response.json()
    if "refresh_token" not in token:
        typer.echo(red("Login failed: no refresh token was granted, so the login cannot be kept"))
        raise typer.Exit(code=1)

    save_credentials(
        token_response_to_credentials(
            token,
            {"client_id": client_id, "token_endpoint": metadata["token_endpoint"]},
        ),
    )
    _choose_default_account(f"✅ Logged in to {base_url}")


def _choose_default_account(logged_in: str) -> None:
    """Save the workspace later commands act in, so a multi-account login works from the start.

    The login is already saved, so nothing here can fail it.
    """
    try:
        accounts = fetch_accounts()
    except typer.Exit:
        typer.echo(green(logged_in))
        typer.echo(yellow("Could not list your accounts, so no default account is set."))
        return
    if len(accounts) == 1:
        _save_default_account(accounts[0])
        typer.echo(green(f"{logged_in} ({accounts[0]['name']})"))
        return
    typer.echo(green(logged_in))
    if not accounts:
        return
    if not can_pick():
        typer.echo(yellow("Your login covers several accounts; run `orchestra accounts use`."))
        return
    typer.echo("Pick a default account:")
    account = pick_account(accounts)
    if account is None:
        typer.echo(yellow("No default account set; run `orchestra accounts use` to pick one."))
        return
    _save_default_account(account)
    typer.echo(green(f"Default account: {account['name']}"))


def _save_default_account(account: dict) -> None:
    # Read again after fetching, which may have refreshed and rotated the saved tokens.
    credentials = load_credentials()
    if credentials is not None:
        save_credentials(
            {**credentials, "account_id": account["id"], "account_name": account["name"]},
        )
