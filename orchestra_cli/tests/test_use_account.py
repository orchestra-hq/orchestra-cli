import json
import time
from types import SimpleNamespace

import click
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src import use_account as use_account_module
from orchestra_cli.src.cli import app
from orchestra_cli.utils.credentials import load_credentials, save_credentials
from tests.conftest import press_keys

runner = CliRunner()

ACCOUNTS_URL = "https://app.getorchestra.io/public/v1/accounts"
PIPELINES_URL = "https://app.getorchestra.io/api/engine/public/pipelines"
TOKEN_ENDPOINT = "https://auth.example/token"
ACCOUNTS = [
    {"id": "acc-1", "name": "Some Great Account"},
    {"id": "acc-2", "name": "Globex"},
]


@pytest.fixture(autouse=True)
def logged_in(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_API_KEY", raising=False)
    monkeypatch.delenv("ORCHESTRA_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("BASE_URL", "")
    save_credentials(
        {
            "client_id": "cli-client",
            "token_endpoint": TOKEN_ENDPOINT,
            "access_token": "login-token",
            "refresh_token": "rt",
            "expires_at": time.time() + 900,
        },
    )


def use(httpx_mock: HTTPXMock, id_or_name: str, accounts: list[dict] = ACCOUNTS):
    httpx_mock.add_response(method="GET", url=ACCOUNTS_URL, json=accounts)
    return runner.invoke(app, ["accounts", "use", id_or_name])


def sent_account_id(httpx_mock: HTTPXMock, args: list[str]) -> str | None:
    httpx_mock.add_response(method="GET", url=PIPELINES_URL, json=[])
    result = runner.invoke(app, ["pipeline", "list", *args])
    assert result.exit_code == 0
    return httpx_mock.get_requests(url=PIPELINES_URL)[-1].headers.get("X-Orchestra-Account-Id")


@pytest.mark.parametrize("id_or_name", ["acc-1", "some great account", "SOME GREAT ACCOUNT"])
def test_use_matches_id_or_case_insensitive_name(httpx_mock: HTTPXMock, id_or_name):
    result = use(httpx_mock, id_or_name)

    assert result.exit_code == 0
    assert "Default account: Some Great Account" in result.output
    credentials = load_credentials()
    assert credentials is not None
    assert credentials["account_id"] == "acc-1"
    assert credentials["account_name"] == "Some Great Account"


def test_use_prefers_id_over_name(httpx_mock: HTTPXMock):
    accounts = [{"id": "acc-1", "name": "acc-2"}, {"id": "acc-2", "name": "Globex"}]

    result = use(httpx_mock, "acc-2", accounts)

    assert result.exit_code == 0
    assert "Default account: Globex" in result.output


def test_use_no_match_lists_names(httpx_mock: HTTPXMock):
    result = use(httpx_mock, "nope")

    assert result.exit_code == 1
    assert "Some Great Account, Globex" in result.output
    assert "account_id" not in (load_credentials() or {})


def test_use_duplicate_name_asks_for_id(httpx_mock: HTTPXMock):
    accounts = [{"id": "acc-1", "name": "Acme"}, {"id": "acc-2", "name": "acme"}]

    result = use(httpx_mock, "ACME", accounts)

    assert result.exit_code == 1
    assert "pass the id" in result.output
    assert "acc-1" in result.output and "acc-2" in result.output
    assert "account_id" not in (load_credentials() or {})


def test_use_requires_login(httpx_mock: HTTPXMock, monkeypatch, tmp_path):
    (tmp_path / ".orchestra" / "credentials.json").unlink()
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")

    result = runner.invoke(app, ["accounts", "use", "acc-1"])

    assert result.exit_code == 1
    assert "orchestra login" in result.output
    assert httpx_mock.get_requests() == []


def test_use_sends_no_account_header(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("ORCHESTRA_ACCOUNT_ID", "acc-env")
    use(httpx_mock, "acc-1")
    use(httpx_mock, "acc-2")

    for request in httpx_mock.get_requests(url=ACCOUNTS_URL):
        assert "X-Orchestra-Account-Id" not in request.headers


def test_commands_send_saved_default_and_flag_and_env_override(httpx_mock: HTTPXMock, monkeypatch):
    assert use(httpx_mock, "acc-1").exit_code == 0

    assert sent_account_id(httpx_mock, []) == "acc-1"
    assert sent_account_id(httpx_mock, ["--account-id", "acc-flag"]) == "acc-flag"
    monkeypatch.setenv("ORCHESTRA_ACCOUNT_ID", "acc-env")
    assert sent_account_id(httpx_mock, []) == "acc-env"


def test_saved_default_is_not_sent_with_api_key(httpx_mock: HTTPXMock, monkeypatch):
    assert use(httpx_mock, "acc-1").exit_code == 0
    credentials = load_credentials()
    assert credentials is not None
    save_credentials({**credentials, "expires_at": time.time() - 1})
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")
    httpx_mock.add_response(method="POST", url=TOKEN_ENDPOINT, status_code=400)

    assert sent_account_id(httpx_mock, []) is None


def test_saved_default_survives_token_refresh(httpx_mock: HTTPXMock):
    assert use(httpx_mock, "acc-1").exit_code == 0
    credentials = load_credentials()
    assert credentials is not None
    save_credentials({**credentials, "expires_at": time.time() + 10})
    httpx_mock.add_response(
        method="POST",
        url=TOKEN_ENDPOINT,
        json={"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 900},
    )

    assert sent_account_id(httpx_mock, []) == "acc-1"
    credentials = load_credentials()
    assert credentials is not None
    assert credentials["access_token"] == "at-new"
    assert credentials["account_id"] == "acc-1"


def test_list_marks_default(httpx_mock: HTTPXMock):
    assert use(httpx_mock, "acc-2").exit_code == 0
    httpx_mock.add_response(method="GET", url=ACCOUNTS_URL, json=ACCOUNTS)

    result = runner.invoke(app, ["accounts", "list"])

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"id": "acc-1", "name": "Some Great Account", "default": False},
        {"id": "acc-2", "name": "Globex", "default": True},
    ]


@pytest.fixture
def terminal(monkeypatch):
    stdin = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(use_account_module, "sys", SimpleNamespace(stdin=stdin))


def pick_with(httpx_mock: HTTPXMock, monkeypatch, *keys: str):
    press_keys(monkeypatch, *keys)
    httpx_mock.add_response(method="GET", url=ACCOUNTS_URL, json=ACCOUNTS)
    return runner.invoke(app, ["accounts", "use"])


@pytest.mark.usefixtures("terminal")
def test_pick_saves_chosen_account(httpx_mock: HTTPXMock, monkeypatch):
    result = pick_with(httpx_mock, monkeypatch, "\x1b[B", "\r")

    assert result.exit_code == 0
    assert "Default account: Globex" in result.output
    assert (load_credentials() or {})["account_id"] == "acc-2"


@pytest.mark.usefixtures("terminal")
def test_pick_starts_on_current_default(httpx_mock: HTTPXMock, monkeypatch):
    assert use(httpx_mock, "acc-2").exit_code == 0

    result = pick_with(httpx_mock, monkeypatch, "\r")

    assert result.exit_code == 0
    assert (load_credentials() or {})["account_id"] == "acc-2"


@pytest.mark.usefixtures("terminal")
@pytest.mark.parametrize("cancel", ["\x1b", "\x03"])
def test_pick_cancel_leaves_default(httpx_mock: HTTPXMock, monkeypatch, cancel):
    assert use(httpx_mock, "acc-1").exit_code == 0

    result = pick_with(httpx_mock, monkeypatch, "\x1b[B", cancel)

    assert result.exit_code == 1
    assert "unchanged" in result.output
    assert (load_credentials() or {})["account_id"] == "acc-1"


def test_pick_without_terminal_exits_with_hint(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setattr(click, "getchar", lambda: pytest.fail("read a key without a terminal"))

    result = runner.invoke(app, ["accounts", "use"])

    assert result.exit_code == 1
    assert "pass a workspace id or name" in result.output
    assert httpx_mock.get_requests() == []
    assert "account_id" not in (load_credentials() or {})
