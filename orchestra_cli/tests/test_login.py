import base64
import hashlib
import json
import threading
import urllib.request
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

import orchestra_cli.src.login as login_module
from orchestra_cli.src.cli import app
from orchestra_cli.utils.credentials import save_credentials

runner = CliRunner()
BASE = "https://app.getorchestra.io"
TOKEN_ENDPOINT = f"{BASE}/oauth/token"
ACCOUNTS_URL = f"{BASE}/public/v1/accounts"
ACCOUNTS = [
    {"id": "acc-1", "name": "Some Great Account"},
    {"id": "acc-2", "name": "Globex"},
]


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("BASE_URL", "")


def mock_authorization_server(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/.well-known/oauth-authorization-server",
        json={
            "authorization_endpoint": f"{BASE}/oauth/authorize",
            "token_endpoint": TOKEN_ENDPOINT,
            "registration_endpoint": f"{BASE}/oauth/register",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/oauth/register",
        status_code=201,
        json={"client_id": "cli-client"},
    )


def mock_login(httpx_mock: HTTPXMock, monkeypatch, **accounts_response):
    """Mock a login that succeeds, then lists accounts with ``accounts_response``."""
    mock_authorization_server(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900},
    )
    httpx_mock.add_response(method="GET", url=ACCOUNTS_URL, **accounts_response)
    fake_browser(monkeypatch, lambda q: {"code": "auth-code", "state": q["state"]})


def cached_credentials(isolated_home) -> dict:
    return json.loads((isolated_home / ".orchestra" / "credentials.json").read_text())[BASE]


def fake_browser(monkeypatch, callback_params):
    """Replace the browser with one that hits the loopback redirect, as consent would.

    ``callback_params`` returns the query for the redirect, or a list of queries to
    send one after another.
    """
    opened = {}
    # No proxy: a loopback request routed through one would never reach the CLI.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def open_url(url):
        query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        opened.update(query)
        calls = callback_params(query)
        targets = [
            f"{query['redirect_uri']}?{urlencode(params)}"
            for params in (calls if isinstance(calls, list) else [calls])
        ]

        def hit_callbacks():
            for target in targets:
                opener.open(target, timeout=5).read()

        threading.Thread(target=hit_callbacks, daemon=True).start()
        return True

    monkeypatch.setattr(webbrowser, "open", open_url)
    # If the callback thread fails, pytest reports its exception; this keeps the
    # test from first sitting out the real five-minute login deadline.
    monkeypatch.setattr(login_module, "LOGIN_TIMEOUT_SECONDS", 10)
    return opened


def test_login_completes_pkce_flow_and_caches_token(
    httpx_mock: HTTPXMock,
    monkeypatch,
    isolated_home,
):
    mock_authorization_server(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900},
    )
    httpx_mock.add_response(method="GET", url=ACCOUNTS_URL, json=ACCOUNTS)
    opened = fake_browser(monkeypatch, lambda q: {"code": "auth-code", "state": q["state"]})

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    assert "Logged in" in result.output
    assert opened["code_challenge_method"] == "S256"
    assert opened["scope"] == "orchestra:read orchestra:write offline_access"
    assert urlparse(opened["redirect_uri"]).hostname == "127.0.0.1"

    token_request = httpx_mock.get_requests(url=TOKEN_ENDPOINT)[0]
    form = {k: v[0] for k, v in parse_qs(token_request.content.decode()).items()}
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "auth-code"
    assert form["redirect_uri"] == opened["redirect_uri"]
    digest = hashlib.sha256(form["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == opened["code_challenge"]

    path = isolated_home / ".orchestra" / "credentials.json"
    assert path.stat().st_mode & 0o777 == 0o600
    cached = json.loads(path.read_text())[BASE]
    assert cached["access_token"] == "at-1"
    assert cached["refresh_token"] == "rt-1"
    assert cached["client_id"] == "cli-client"


def test_login_ignores_callback_with_foreign_state(httpx_mock: HTTPXMock, monkeypatch):
    mock_authorization_server(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 900},
    )
    httpx_mock.add_response(method="GET", url=ACCOUNTS_URL, json=ACCOUNTS)
    fake_browser(
        monkeypatch,
        lambda q: [
            {"code": "forged-code", "state": "forged"},
            {"code": "auth-code", "state": q["state"]},
        ],
    )

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    form = parse_qs(httpx_mock.get_requests(url=TOKEN_ENDPOINT)[0].content.decode())
    assert form["code"] == ["auth-code"]


def test_login_without_refresh_token_fails_cleanly(
    httpx_mock: HTTPXMock,
    monkeypatch,
    isolated_home,
):
    mock_authorization_server(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        json={"access_token": "at-1", "expires_in": 900},
    )
    fake_browser(monkeypatch, lambda q: {"code": "auth-code", "state": q["state"]})

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "no refresh token was granted" in result.output
    assert not (isolated_home / ".orchestra" / "credentials.json").exists()


def test_login_reports_denied_consent(httpx_mock: HTTPXMock, monkeypatch):
    mock_authorization_server(httpx_mock)
    fake_browser(
        monkeypatch,
        lambda q: {"error": "access_denied", "error_description": "denied", "state": q["state"]},
    )

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "Login failed: denied" in result.output


def test_login_explains_host_without_authorization_server(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/.well-known/oauth-authorization-server",
        text="<!doctype html><html></html>",
        headers={"Content-Type": "text/html"},
    )

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "does not support `orchestra login`" in result.output


def test_login_clears_default_account(httpx_mock: HTTPXMock, monkeypatch, isolated_home):
    save_credentials({"access_token": "at-0", "account_id": "acc-1", "account_name": "Acme"})
    mock_login(httpx_mock, monkeypatch, json=ACCOUNTS)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    cached = cached_credentials(isolated_home)
    assert cached["access_token"] == "at-1"
    assert "account_id" not in cached
    assert "account_name" not in cached


def test_login_saves_only_account_as_default(httpx_mock: HTTPXMock, monkeypatch, isolated_home):
    mock_login(httpx_mock, monkeypatch, json=ACCOUNTS[:1])

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    assert f"✅ Logged in to {BASE} (Some Great Account)" in result.output
    cached = cached_credentials(isolated_home)
    assert cached["access_token"] == "at-1"
    assert cached["account_id"] == "acc-1"
    assert cached["account_name"] == "Some Great Account"
    accounts_request = httpx_mock.get_requests(url=ACCOUNTS_URL)[0]
    assert accounts_request.headers["Authorization"] == "Bearer at-1"


@pytest.fixture
def fake_picker(monkeypatch):
    """Pretend to be in a terminal, with a picker that returns the account set in ``choice``."""
    choice = {}
    monkeypatch.setattr(login_module, "can_pick", lambda: True)
    monkeypatch.setattr(login_module, "pick_account", lambda _accounts: choice.get("account"))
    return choice


def test_login_picks_default_from_several(
    httpx_mock: HTTPXMock,
    monkeypatch,
    isolated_home,
    fake_picker,
):
    fake_picker["account"] = ACCOUNTS[1]
    mock_login(httpx_mock, monkeypatch, json=ACCOUNTS)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    assert "Default account: Globex" in result.output
    assert cached_credentials(isolated_home)["account_id"] == "acc-2"


@pytest.mark.usefixtures("fake_picker")
def test_login_cancelled_pick_keeps_login(httpx_mock: HTTPXMock, monkeypatch, isolated_home):
    mock_login(httpx_mock, monkeypatch, json=ACCOUNTS)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    assert "No default account set" in result.output
    cached = cached_credentials(isolated_home)
    assert cached["access_token"] == "at-1"
    assert "account_id" not in cached


def test_login_with_several_accounts_without_terminal_hints(
    httpx_mock: HTTPXMock,
    monkeypatch,
    isolated_home,
):
    monkeypatch.setattr(
        login_module,
        "pick_account",
        lambda _accounts: pytest.fail("prompted without a terminal"),
    )
    mock_login(httpx_mock, monkeypatch, json=ACCOUNTS)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    assert "orchestra accounts use" in result.output
    assert "account_id" not in cached_credentials(isolated_home)


@pytest.mark.parametrize(
    "accounts_response",
    [{"status_code": 500, "json": {"detail": "boom"}}, {"text": "not json"}],
)
def test_login_survives_failed_accounts_fetch(
    httpx_mock: HTTPXMock,
    monkeypatch,
    isolated_home,
    accounts_response,
):
    mock_login(httpx_mock, monkeypatch, **accounts_response)

    result = runner.invoke(app, ["login"])

    assert result.exit_code == 0, result.output
    assert f"✅ Logged in to {BASE}" in result.output
    assert "no default account is set" in result.output
    cached = cached_credentials(isolated_home)
    assert cached["access_token"] == "at-1"
    assert "account_id" not in cached
