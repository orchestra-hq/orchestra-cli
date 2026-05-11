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
