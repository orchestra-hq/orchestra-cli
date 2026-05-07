from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app
from tests.conftest import make_git_subprocess_mock

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")
    monkeypatch.setenv("BASE_URL", "")


def test_get_pipeline_success_by_alias(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "id": "pipe-1",
            "alias": "demo",
            "name": "Demo pipeline",
            "latestRunStatus": "SUCCEEDED",
        },
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "get", "--alias", "demo"])

    assert result.exit_code == 0
    assert result.output == (
        "Pipeline\n"
        "  ID: pipe-1\n"
        "  Alias: demo\n"
        "  Name: Demo pipeline\n"
        "  Latest Run Status: SUCCEEDED\n"
    )


def test_get_pipeline_humanizes_abbreviations_without_corrupting_words(
    httpx_mock: HTTPXMock,
):
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json={
            "identity": "external-key",
            "api_url": "https://example.com",
            "idle_timeout": 30,
            "yaml_path": "pipe.yaml",
        },
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "get", "--alias", "demo"])

    assert result.exit_code == 0
    assert "  Identity: external-key" in result.output
    assert "  API URL: https://example.com" in result.output
    assert "  Idle Timeout: 30" in result.output
    assert "  YAML Path: pipe.yaml" in result.output
    assert "IDentity" not in result.output
    assert "IDle" not in result.output


def test_get_pipeline_success_by_pipeline_id(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?pipeline_id=pipeline-id",
        json={"id": "pipeline-id", "alias": "demo"},
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "get", "--pipeline-id", "pipeline-id"])

    assert result.exit_code == 0
    assert "ID: pipeline-id" in result.output
    assert "Alias: demo" in result.output


def test_get_pipeline_success_by_path_inside_git(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    def respond(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params.multi_items()) == {
            "repository": "org/repo",
            "yaml_path": "pipe.yaml",
        }
        assert request.headers["Authorization"] == "Bearer fake-key"
        return httpx.Response(200, json={"id": "pipe-1", "repository": "org/repo"})

    httpx_mock.add_callback(respond, method="GET")

    result = runner.invoke(app, ["pipeline", "get", "--path", str(yaml_file)])

    assert result.exit_code == 0
    assert "Repository: org/repo" in result.output


def test_get_pipeline_requires_selector():
    result = runner.invoke(app, ["pipeline", "get"])

    assert result.exit_code == 1
    assert "Provide one of --alias, --pipeline-id, or --path" in result.output


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


def test_get_pipeline_rejects_non_object_success_json(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=demo",
        json=[],
        status_code=200,
        match_headers={"Authorization": "Bearer fake-key"},
    )

    result = runner.invoke(app, ["pipeline", "get", "--alias", "demo"])

    assert result.exit_code == 1
    assert "success response was not a JSON object" in result.output
