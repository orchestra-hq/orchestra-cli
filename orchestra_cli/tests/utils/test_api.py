import time
from urllib.parse import parse_qs

import pytest
import typer
from pytest_httpx import HTTPXMock

from orchestra_cli.utils.api import require_api_key
from orchestra_cli.utils.credentials import load_credentials, save_credentials

TOKEN_ENDPOINT = "https://app.getorchestra.io/oauth/token"


@pytest.fixture(autouse=True)
def logged_in(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_API_KEY", raising=False)
    monkeypatch.setenv("BASE_URL", "")


def cache_login(expires_at: float):
    save_credentials(
        {
            "client_id": "cli-client",
            "token_endpoint": TOKEN_ENDPOINT,
            "access_token": "at-old",
            "refresh_token": "rt-old",
            "expires_at": expires_at,
        },
    )


def test_api_key_wins_over_cached_login(monkeypatch):
    cache_login(time.time() + 900)
    monkeypatch.setenv("ORCHESTRA_API_KEY", "account-key")

    assert require_api_key() == "account-key"


def test_uses_cached_token_while_fresh():
    cache_login(time.time() + 900)

    assert require_api_key() == "at-old"


def test_refreshes_expiring_token_and_stores_rotated_refresh_token(httpx_mock: HTTPXMock):
    cache_login(time.time() + 10)
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        json={"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 900},
    )

    assert require_api_key() == "at-new"

    form = parse_qs(httpx_mock.get_requests()[0].content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["rt-old"]
    cached = load_credentials()
    assert cached is not None
    assert cached["refresh_token"] == "rt-new"


def test_rejected_refresh_asks_user_to_log_in_again(httpx_mock: HTTPXMock, capsys):
    cache_login(time.time() - 1)
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        status_code=400,
        json={"error": "invalid_grant"},
    )

    with pytest.raises(typer.Exit):
        require_api_key()
    assert "orchestra login" in capsys.readouterr().out


def test_login_for_another_host_is_not_used(monkeypatch):
    cache_login(time.time() + 900)
    monkeypatch.setenv("BASE_URL", "https://stage.getorchestra.io")

    with pytest.raises(typer.Exit):
        require_api_key()
