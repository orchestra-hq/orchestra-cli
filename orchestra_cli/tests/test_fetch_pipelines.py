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


def test_get_pipeline_success_by_alias(httpx_mock: HTTPXMock):
    pipeline = {
        "id": "pipe-1",
        "alias": "demo",
        "name": "Demo pipeline",
        "latestRunStatus": "SUCCEEDED",
    }
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json=pipeline,
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "get", "--alias", "demo"])

    assert result.exit_code == 0
    assert result.output == f"{json.dumps(pipeline, indent=2)}\n"


def test_get_pipeline_requires_selector():
    result = runner.invoke(app, ["pipeline", "get"])

    assert result.exit_code == 1
    assert "Provide one of --alias, --pipeline-id, or --path" in result.output


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


def test_get_pipeline_missing_api_key(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_API_KEY", raising=False)

    result = runner.invoke(app, ["pipeline", "get", "--alias", "demo"])

    assert result.exit_code == 1
    assert "ORCHESTRA_API_KEY is not set" in result.output


def test_get_pipeline_api_error(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={"detail": "Forbidden"},
        status_code=403,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "get", "--alias", "demo"])

    assert result.exit_code == 1
    assert "Get pipeline failed with status 403" in result.output
    assert "Forbidden" in result.output


def test_get_pipeline_invalid_success_json(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        text="ok",
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "get", "--alias", "demo"])

    assert result.exit_code == 1
    assert "success response was not valid JSON" in result.output
