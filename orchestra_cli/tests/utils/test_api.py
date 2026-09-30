import time
from urllib.parse import parse_qs

import httpx
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


def test_login_wins_over_api_key(monkeypatch):
    cache_login(time.time() + 900)
    monkeypatch.setenv("ORCHESTRA_API_KEY", "account-key")

    assert require_api_key() == "at-old"


def test_api_key_is_used_when_not_logged_in(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", "account-key")

    assert require_api_key() == "account-key"


def test_expired_login_falls_back_to_api_key(httpx_mock: HTTPXMock, monkeypatch, capsys):
    cache_login(time.time() - 1)
    monkeypatch.setenv("ORCHESTRA_API_KEY", "account-key")
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        status_code=400,
        json={"error": "invalid_grant"},
    )

    assert require_api_key() == "account-key"
    assert "using ORCHESTRA_API_KEY" in capsys.readouterr().out


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
    assert cached["access_token"] == "at-new"
    assert cached["refresh_token"] == "rt-new"
    assert require_api_key() == "at-new"


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


def test_refresh_server_error_is_not_reported_as_expired_login(httpx_mock: HTTPXMock, capsys):
    cache_login(time.time() - 1)
    httpx_mock.add_response(method="POST", url=TOKEN_ENDPOINT, status_code=503)

    with pytest.raises(typer.Exit):
        require_api_key()
    output = capsys.readouterr().out
    assert "Token refresh failed with status 503" in output
    assert "expired" not in output


def test_rejected_refresh_uses_token_another_process_just_rotated_in(httpx_mock: HTTPXMock):
    cache_login(time.time() - 1)

    def other_process_refreshes_first(_request):
        save_credentials(
            {
                "client_id": "cli-client",
                "token_endpoint": TOKEN_ENDPOINT,
                "access_token": "at-other",
                "refresh_token": "rt-other",
                "expires_at": time.time() + 900,
            },
        )
        return httpx.Response(400, json={"error": "invalid_grant"})

    httpx_mock.add_callback(other_process_refreshes_first, method="POST", url=TOKEN_ENDPOINT)

    assert require_api_key() == "at-other"


@pytest.mark.parametrize("failure", ["network", "server"])
def test_refresh_outage_keeps_token_that_has_not_lapsed(httpx_mock: HTTPXMock, failure):
    cache_login(time.time() + 30)
    if failure == "network":
        httpx_mock.add_exception(httpx.ConnectError("unreachable"), url=TOKEN_ENDPOINT)
    else:
        httpx_mock.add_response(method="POST", url=TOKEN_ENDPOINT, status_code=503)

    assert require_api_key() == "at-old"


def test_refresh_network_error_on_lapsed_token_exits(httpx_mock: HTTPXMock, capsys):
    cache_login(time.time() - 1)
    httpx_mock.add_exception(httpx.ConnectError("unreachable"), url=TOKEN_ENDPOINT)

    with pytest.raises(typer.Exit):
        require_api_key()
    assert "HTTP request failed" in capsys.readouterr().out
