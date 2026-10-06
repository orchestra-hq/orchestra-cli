import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()
mock_api_key = "fake-key"


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", mock_api_key)
    monkeypatch.setenv("BASE_URL", "")


def test_delete_success(httpx_mock: HTTPXMock):
    alias = "demo"
    httpx_mock.add_response(
        method="DELETE",
        url="https://app.getorchestra.io/api/engine/public/pipelines?alias=demo",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        status_code=204,
    )

    result = runner.invoke(app, ["pipeline", "delete", "--alias", alias], input="y\n")

    assert result.exit_code == 0
    assert "Delete pipeline (alias: demo)?" in result.output
    assert "deleted successfully" in result.output


def test_delete_uuid_like_alias_uses_alias_query(httpx_mock: HTTPXMock):
    alias = "798d7121-6809-4148-aecb-26740cfabdf1"
    httpx_mock.add_response(
        method="DELETE",
        url=f"https://app.getorchestra.io/api/engine/public/pipelines?alias={alias}",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        status_code=204,
    )

    result = runner.invoke(app, ["pipeline", "delete", "--alias", alias], input="y\n")

    assert result.exit_code == 0
    assert "deleted successfully" in result.output


def test_delete_pipeline_id_uses_query_selector(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="DELETE",
        url="https://app.getorchestra.io/api/engine/public/pipelines?pipeline_id=pipeline-id",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        status_code=204,
    )

    result = runner.invoke(
        app,
        ["pipeline", "delete", "--pipeline-id", "pipeline-id"],
        input="y\n",
    )

    assert result.exit_code == 0
    assert "pipeline_id: pipeline-id" in result.output


def test_delete_aborts_without_confirmation(httpx_mock: HTTPXMock):
    result = runner.invoke(app, ["pipeline", "delete", "--alias", "demo"], input="n\n")

    assert result.exit_code == 1
    assert "Delete pipeline (alias: demo)?" in result.output
    assert "Deletion aborted" in result.output
    assert httpx_mock.get_requests() == []


def test_delete_requires_selector():
    result = runner.invoke(app, ["pipeline", "delete"])

    assert result.exit_code == 1
    assert "Provide one of --alias, --pipeline-id, or --path" in result.output


def test_delete_missing_api_key(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_API_KEY", raising=False)

    result = runner.invoke(app, ["pipeline", "delete", "--alias", "demo"], input="y\n")

    assert result.exit_code == 1
    assert "ORCHESTRA_API_KEY is not set" in result.output


def test_delete_http_request_failure(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.TimeoutException("timed out"), method="DELETE")

    result = runner.invoke(app, ["pipeline", "delete", "--alias", "demo"], input="y\n")

    assert result.exit_code == 1
    assert "HTTP request failed" in result.output


def test_delete_api_error(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="DELETE",
        url="https://app.getorchestra.io/api/engine/public/pipelines?alias=demo",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "Pipeline not found"},
        status_code=404,
    )

    result = runner.invoke(app, ["pipeline", "delete", "--alias", "demo"], input="y\n")

    assert result.exit_code == 1
    assert "Delete failed with status 404" in result.output
    assert "Pipeline not found" in result.output
