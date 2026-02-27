from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", "fake-key")
    monkeypatch.setenv("BASE_URL", "")


def test_update_success_default_no_publish(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        json={"id": "pipeline-id"},
        status_code=200,
        match_json={
            "data": {"name": "demo", "version": 1},
            "published": False,
            "storage_provider": "ORCHESTRA",
        },
    )

    result = runner.invoke(app, ["update-pipeline", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 0
    assert "updated successfully" in result.output


def test_update_publish_flag(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        json={"id": "pipeline-id"},
        status_code=200,
        match_json={
            "data": {"name": "demo", "version": 1},
            "published": True,
            "storage_provider": "ORCHESTRA",
        },
    )

    result = runner.invoke(
        app,
        ["update-pipeline", "--alias", "demo", "--path", str(yaml_file), "--publish"],
    )
    assert result.exit_code == 0
    assert "updated successfully" in result.output


def test_update_missing_api_key(monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")

    monkeypatch.delenv("ORCHESTRA_API_KEY", raising=False)
    result = runner.invoke(app, ["update-pipeline", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "ORCHESTRA_API_KEY is not set" in result.output


def test_update_invalid_yaml(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [oops\n")

    result = runner.invoke(app, ["update-pipeline", "--alias", "demo", "--path", str(bad)])
    assert result.exit_code == 1
    assert "Invalid YAML" in result.output


def test_update_schema_validation_error(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"detail": [{"loc": ["root"], "msg": "bad"}]},
        status_code=400,
    )

    result = runner.invoke(app, ["update-pipeline", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "Validation failed" in result.output


def test_update_api_error_orchestra_backed_only(tmp_path: Path, httpx_mock: HTTPXMock):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\nversion: 1\n")

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="PUT",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo",
        json={"detail": "Only orchestra-backed pipelines can be updated via this endpoint."},
        status_code=400,
    )

    result = runner.invoke(app, ["update-pipeline", "--alias", "demo", "--path", str(yaml_file)])
    assert result.exit_code == 1
    assert "Update failed" in result.output
    assert "Only orchestra-backed pipelines can be updated via this endpoint." in result.output
