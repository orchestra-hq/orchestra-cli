import json

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")
    monkeypatch.setenv("BASE_URL", "")


def test_fetch_pipelines_legacy_success(httpx_mock: HTTPXMock):
    pipelines = [
        {
            "id": "pipe-1",
            "alias": "demo",
            "name": "Demo pipeline",
            "latestRunStatus": "SUCCEEDED",
        },
    ]
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json=pipelines,
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["fetch-pipelines"])

    assert result.exit_code == 0
    assert result.output == f"{json.dumps(pipelines, indent=2)}\n"


def test_list_pipelines_success(httpx_mock: HTTPXMock):
    pipelines = [
        {
            "id": "pipe-1",
            "alias": "demo",
            "name": "Demo pipeline",
            "latestRunStatus": "SUCCEEDED",
        },
    ]
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json=pipelines,
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "list"])

    assert result.exit_code == 0
    assert result.output == f"{json.dumps(pipelines, indent=2)}\n"


@pytest.mark.parametrize(
    ("args", "env_account_id", "expected_account_id"),
    [
        (["--account-id", "acc-flag"], "acc-env", "acc-flag"),
        ([], "acc-env", "acc-env"),
        ([], None, None),
    ],
)
def test_list_pipelines_account_id_header(
    httpx_mock: HTTPXMock,
    monkeypatch,
    args,
    env_account_id,
    expected_account_id,
):
    if env_account_id:
        monkeypatch.setenv("ORCHESTRA_ACCOUNT_ID", env_account_id)
    else:
        monkeypatch.delenv("ORCHESTRA_ACCOUNT_ID", raising=False)
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipelines",
        json=[],
    )

    result = runner.invoke(app, ["pipeline", "list", *args])

    assert result.exit_code == 0
    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers.get("X-Orchestra-Account-Id") == expected_account_id


def test_list_pipelines_help_shows_account_id():
    result = runner.invoke(app, ["pipeline", "list", "--help"])

    assert result.exit_code == 0
    assert "--account-id" in result.output
