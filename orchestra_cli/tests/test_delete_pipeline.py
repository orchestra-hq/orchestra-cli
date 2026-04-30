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
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        status_code=204,
    )

    result = runner.invoke(app, ["pipeline", "delete", "--alias", alias])

    assert result.exit_code == 0
    assert "deleted successfully" in result.output


def test_delete_uuid_like_alias_uses_alias_path(httpx_mock: HTTPXMock):
    alias = "798d7121-6809-4148-aecb-26740cfabdf1"
    httpx_mock.add_response(
        method="DELETE",
        url=f"https://app.getorchestra.io/api/engine/public/pipelines/{alias}",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        status_code=204,
    )

    result = runner.invoke(app, ["pipeline", "delete", "--alias", alias])

    assert result.exit_code == 0
    assert "deleted successfully" in result.output


def test_delete_missing_api_key(monkeypatch):
    monkeypatch.delenv("ORCHESTRA_API_KEY", raising=False)

    result = runner.invoke(app, ["pipeline", "delete", "--alias", "demo"])

    assert result.exit_code == 1
    assert "ORCHESTRA_API_KEY is not set" in result.output


def test_delete_http_request_failure(monkeypatch):
    def raise_timeout(*args, **kwargs):  # noqa: ARG001
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "delete", raise_timeout)

    result = runner.invoke(app, ["pipeline", "delete", "--alias", "demo"])

    assert result.exit_code == 1
    assert "HTTP request failed" in result.output


def test_delete_api_error(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="DELETE",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "Pipeline not found"},
        status_code=404,
    )

    result = runner.invoke(app, ["pipeline", "delete", "--alias", "demo"])

    assert result.exit_code == 1
    assert "Delete failed with status 404" in result.output
    assert "Pipeline not found" in result.output
