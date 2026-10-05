import json
import time

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app
from orchestra_cli.utils.credentials import save_credentials

runner = CliRunner()

ACCOUNTS_URL = "https://app.getorchestra.io/api/engine/public/accounts"


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")
    monkeypatch.setenv("BASE_URL", "")


def test_list_accounts_success(httpx_mock: HTTPXMock):
    accounts = [{"id": "acc-1", "name": "Acme"}, {"id": "acc-2", "name": "Globex"}]
    httpx_mock.add_response(
        method="GET",
        url=ACCOUNTS_URL,
        json=accounts,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["accounts", "list"])

    assert result.exit_code == 0
    assert result.output == f"{json.dumps(accounts, indent=2)}\n"


def test_list_accounts_uses_login_token(httpx_mock: HTTPXMock):
    save_credentials(
        {
            "client_id": "cli-client",
            "token_endpoint": "https://auth.example/token",
            "access_token": "login-token",
            "refresh_token": "rt",
            "expires_at": time.time() + 900,
        },
    )
    accounts = [{"id": "acc-1", "name": "Acme"}, {"id": "acc-2", "name": "Globex"}]
    httpx_mock.add_response(
        method="GET",
        url=ACCOUNTS_URL,
        json=accounts,
        match_headers={"Authorization": "Bearer login-token"},
    )

    result = runner.invoke(app, ["accounts", "list"])

    assert result.exit_code == 0
    assert result.output == f"{json.dumps(accounts, indent=2)}\n"


def test_list_accounts_error_status(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=ACCOUNTS_URL,
        status_code=401,
        json={"detail": "Unauthorized"},
    )

    result = runner.invoke(app, ["accounts", "list"])

    assert result.exit_code == 1
    assert "List accounts failed with status 401" in result.output
    assert "Unauthorized" in result.output


def test_list_accounts_sends_no_account_header(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=ACCOUNTS_URL, json=[])

    result = runner.invoke(app, ["accounts", "list"])

    assert result.exit_code == 0
    request = httpx_mock.get_request()
    assert request is not None
    assert "X-Orchestra-Account-Id" not in request.headers
