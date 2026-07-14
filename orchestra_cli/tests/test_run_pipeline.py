from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import typer
from pytest_httpx import HTTPXMock
from rich.console import Console
from typer.testing import CliRunner

import orchestra_cli.src.run_pipeline as run_pipeline_module
from orchestra_cli.src.cli import app
from orchestra_cli.src.run_pipeline import (
    _build_live_status_text,
    _build_poll_status_text,
    _build_task_runs_table,
    _format_pipeline_duration,
    _format_task_run_timing,
    _parse_created_at_utc,
    _resolve_start_path,
    _typed_environment_override,
    build_run_payload,
)
from orchestra_cli.utils.pipeline_selector import PipelineSelector
from orchestra_cli.utils.pipeline_update import build_update_selector
from tests.conftest import make_git_subprocess_mock

runner = CliRunner()
mock_pipeline_run_id = "798d7121-6809-4148-aecb-26740cfabdf1"
mock_api_key = "fake-key"


def test_build_run_payload_includes_version_number_when_set() -> None:
    payload = build_run_payload(branch="main", commit="abc", version_number=9)
    assert payload == {
        "branch": "main",
        "commit": "abc",
        "versionNumber": 9,
    }


def test_build_run_payload_omits_version_number_when_not_set() -> None:
    payload = build_run_payload()
    assert "versionNumber" not in payload
    assert payload == {}


def test_build_run_payload_includes_task_environment_and_overrides() -> None:
    payload = build_run_payload(
        version_number=3,
        environment="staging",
        run_inputs={"foo": "bar"},
        environment_overrides={"FLAG": {"type": "bool", "value": True}},
        task_ids=["task_1", "task_2"],
        continue_downstream_run=False,
    )
    assert payload == {
        "versionNumber": 3,
        "environment": "staging",
        "runInputs": {"foo": "bar"},
        "environmentOverrides": {"FLAG": {"type": "bool", "value": True}},
        "taskIds": ["task_1", "task_2"],
        "continueDownstreamRun": False,
    }


def test_typed_environment_override_treats_non_parseable_unicode_digit_as_string() -> None:
    override = _typed_environment_override("²")

    assert override == {"type": "string", "value": "²"}


def test_parse_created_at_utc_reads_iso_timestamp() -> None:
    parsed = _parse_created_at_utc({"createdAt": "2026-05-29T11:30:00Z"})
    assert parsed == datetime(2026, 5, 29, 11, 30, 0, tzinfo=UTC)


def test_parse_created_at_utc_reads_nested_pipeline_run_timestamp() -> None:
    parsed = _parse_created_at_utc(
        {"pipelineRun": {"createdAt": "2026-05-29T11:30:00+00:00"}},
    )
    assert parsed == datetime(2026, 5, 29, 11, 30, 0, tzinfo=UTC)


def test_format_pipeline_duration_uses_human_readable_minutes() -> None:
    created_at = datetime(2026, 5, 29, 11, 30, 0, tzinfo=UTC)
    now_utc = datetime(2026, 5, 29, 11, 31, 30, tzinfo=UTC)
    assert _format_pipeline_duration(created_at, now_utc) == "1:30 minutes"


def test_build_poll_status_text_includes_duration() -> None:
    created_at = datetime(2026, 5, 29, 11, 30, 0, tzinfo=UTC)
    now_utc = datetime(2026, 5, 29, 11, 31, 30, tzinfo=UTC)
    text = _build_poll_status_text("RUNNING", created_at, now_utc)
    assert text.plain == "Pipeline status: RUNNING (1:30 minutes)"


def test_build_live_status_text_includes_update_age() -> None:
    text = _build_live_status_text(3)
    assert text.plain == "Live status (updated 3 seconds ago)"


def test_resolve_start_path_uses_existing_pipeline_id_when_selector_has_no_alias() -> None:
    selector = PipelineSelector(repository="org/repo", yaml_path="pipe.yaml")

    assert _resolve_start_path(selector, {"id": "pipeline-id"}) == "pipelines/pipeline-id/start"


def test_resolve_start_path_requires_identifier_when_existing_pipeline_missing_id() -> None:
    selector = PipelineSelector(repository="org/repo", yaml_path="pipe.yaml")

    with pytest.raises(typer.Exit) as exc_info:
        _resolve_start_path(selector, {"pipeline_id": "legacy-id"})

    assert exc_info.value.exit_code == 1


def test_resolve_start_path_requires_identifier_when_no_selector_or_existing_pipeline() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        _resolve_start_path(PipelineSelector())

    assert exc_info.value.exit_code == 1


def test_build_update_selector_uses_alias_when_pipeline_id_is_not_a_string() -> None:
    selector = build_update_selector({"id": 123, "alias": "demo"}, "Run")

    assert selector == PipelineSelector(alias="demo")


def test_format_task_run_timing_prefers_started_and_completed_window() -> None:
    timing = _format_task_run_timing(
        {
            "createdAt": "2026-05-29T11:29:00Z",
            "startedAt": "2026-05-29T11:30:00Z",
            "completedAt": "2026-05-29T11:31:30Z",
        },
    )
    assert timing == "ran for 1:30 minutes"


def test_build_task_runs_table_renders_status_and_timing() -> None:
    renderable = _build_task_runs_table(
        [
            {
                "id": "tr-123",
                "taskName": "Extract customers",
                "status": "RUNNING",
                "createdAt": "2026-05-29T11:29:00Z",
                "startedAt": "2026-05-29T11:30:00Z",
                "message": "Loading source data",
            },
        ],
        can_fetch_task_runs=True,
        now_utc=datetime(2026, 5, 29, 11, 31, 30, tzinfo=UTC),
    )
    console = Console(record=True, width=120)
    console.print(renderable)
    output = console.export_text()

    assert "Extract customers" in output
    assert "tr-123" in output
    assert "RUNNING" in output
    assert "running for 1:30" in output
    assert "minute" in output
    assert "Loading source data" in output


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", mock_api_key)
    monkeypatch.setenv("BASE_URL", "")


def test_run_success_simple(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    # Mock git repo to trigger no warnings
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": mock_pipeline_run_id},
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--no-wait"])
    assert result.exit_code == 0
    assert (
        result.output.strip()
        == f"Starting pipeline (alias: demo)\nStarted pipeline (alias: demo), run id: {mock_pipeline_run_id}"  # noqa: E501
    )


def test_run_continue_requires_task() -> None:
    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--continue", "--no-wait"])
    assert result.exit_code == 1
    assert "--continue can only be used when --task/-t is provided" in result.output


def test_run_rejects_both_environment_id_and_name() -> None:
    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--alias",
            "demo",
            "--environment-id",
            "env-123",
            "--environment-name",
            "staging",
            "--no-wait",
        ],
    )
    assert result.exit_code == 1
    assert "Provide only one of --environment-id or --environment-name" in result.output


def test_run_rejects_alias_with_path(tmp_path: Path) -> None:
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")

    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--alias",
            "demo",
            "--path",
            str(yaml_file),
            "--no-wait",
        ],
    )

    assert result.exit_code == 1
    assert "--path cannot be used with --alias/-a for pipeline run" in result.output


def test_run_rejects_pipeline_id_with_path(tmp_path: Path) -> None:
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")

    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--pipeline-id",
            "pipe-123",
            "--path",
            str(yaml_file),
            "--no-wait",
        ],
    )

    assert result.exit_code == 1
    assert "--path cannot be used with --pipeline-id/-i for pipeline run" in result.output


def test_run_with_task_and_overrides(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo",
        text="\n".join(
            [
                "name: demo",
                "pipeline:",
                "  task_group_1:",
                "    tasks:",
                "      task_1:",
                "        name: Task One",
            ],
        ),
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "versionNumber": 7,
            "taskIds": ["task_1"],
            "continueDownstreamRun": True,
            "environment": "staging",
            "runInputs": {"input_1": "value-1", "input_2": "42"},
            "environmentOverrides": {
                "BOOL_FLAG": {"type": "bool", "value": True},
                "RETRIES": {"type": "int", "value": 3},
            },
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--alias",
            "demo",
            "--task",
            "task_1",
            "--continue",
            "--version-number",
            "7",
            "--environment-name",
            "staging",
            "--input",
            "input_1=value-1",
            "--input",
            "input_2=42",
            "-e",
            "BOOL_FLAG=true",
            "-e",
            "RETRIES=3",
            "--no-wait",
        ],
    )
    assert result.exit_code == 0
    assert f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}" in result.output


def test_run_task_name_resolves_from_remote_pipeline_data(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo",
        text="\n".join(
            [
                "name: demo",
                "pipeline:",
                "  task_group_1:",
                "    tasks:",
                "      task_1:",
                "        name: Task One",
                "      task_2:",
                "        name: Task Two",
            ],
        ),
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "taskIds": ["task_1"],
            "continueDownstreamRun": False,
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "run", "--alias", "demo", "--task", "Task One", "--no-wait"],
    )

    assert result.exit_code == 0
    assert f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}" in result.output


def test_run_task_name_resolves_from_remote_json_pipeline_definition(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo",
        json={
            "name": "demo",
            "pipeline": {
                "task_group_1": {
                    "tasks": {
                        "task_1": {"name": "Task One"},
                        "task_2": {"name": "Task Two"},
                    },
                },
            },
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "taskIds": ["task_1"],
            "continueDownstreamRun": False,
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "run", "--alias", "demo", "--task", "Task One", "--no-wait"],
    )

    assert result.exit_code == 0
    assert f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}" in result.output


def test_run_task_name_ignores_metadata_only_wrapper_and_uses_top_level_pipeline(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline/data?alias=demo",
        json={
            "data": {"page": 1, "total": 1},
            "pipeline": {
                "task_group_1": {
                    "tasks": {
                        "task_1": {"name": "Task One"},
                    },
                },
            },
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "taskIds": ["task_1"],
            "continueDownstreamRun": False,
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "run", "--alias", "demo", "--task", "Task One", "--no-wait"],
    )

    assert result.exit_code == 0
    assert f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}" in result.output


def test_run_task_group_resolves_from_yaml(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text(
        "\n".join(
            [
                "name: demo",
                "pipeline:",
                "  task_group_1:",
                "    tasks:",
                "      task_1:",
                "        name: Task One",
                "      task_2:",
                "        name: Task Two",
            ],
        ),
    )
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/pipeline-id/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={
            "taskIds": ["task_1", "task_2"],
            "continueDownstreamRun": False,
        },
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )
    result = runner.invoke(
        app,
        ["pipeline", "run", "--path", str(yaml_file), "--task", "task_group_1", "--no-wait"],
    )
    assert result.exit_code == 0
    assert (
        f"Started pipeline (repository: org/repo, yaml_path: pipe.yaml), "
        f"run id: {mock_pipeline_run_id}" in result.output
    )


def test_run_path_lookup_uses_existing_pipeline_id(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "storage_provider": "ORCHESTRA"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/pipeline-id/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--path", str(yaml_file), "--no-wait"])

    assert result.exit_code == 0
    assert (
        f"Started pipeline (repository: org/repo, yaml_path: pipe.yaml), "
        f"run id: {mock_pipeline_run_id}" in result.output
    )


def test_run_path_lookup_requires_pipeline_identifier(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"storage_provider": "ORCHESTRA"},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--path", str(yaml_file), "--no-wait"])

    assert result.exit_code == 1
    assert "failed to load pipeline id" in result.output


def test_run_path_lookup_rejects_invalid_json_success_response(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        text="not json",
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--path", str(yaml_file), "--no-wait"])

    assert result.exit_code == 1
    assert "pipeline lookup response was not valid JSON" in result.output


def test_run_path_lookup_rejects_empty_json_object_success_response(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--path", str(yaml_file), "--no-wait"])

    assert result.exit_code == 1
    assert "pipeline lookup response was empty" in result.output


def test_run_with_branch_commit(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"branch": "main", "commit": "deadbeef"},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=201,
    )

    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--alias",
            "demo",
            "--branch",
            "main",
            "--commit",
            "deadbeef",
            "--no-wait",
        ],
    )
    assert result.exit_code == 0
    assert (
        result.output.strip()
        == f"Starting pipeline (alias: demo)\nStarted pipeline (alias: demo), run id: {mock_pipeline_run_id}"  # noqa: E501
    )


def test_run_success_by_pipeline_id(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/pipeline-id/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "run", "--pipeline-id", "pipeline-id", "--no-wait"],
    )
    assert result.exit_code == 0
    assert (
        f"Started pipeline (pipeline_id: pipeline-id), run id: {mock_pipeline_run_id}"
        in result.output
    )


def test_run_warnings_prompt(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, " M file.txt\n", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-parse", "HEAD"): (0, "aaaa", ""),
        ("rev-parse", "@{u}"): (0, "bbbb", ""),
        ("status", "-sb"): (0, "## main...origin/main [behind 1]", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    # Simulate pressing Enter
    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--no-wait"], input="\n")
    assert result.exit_code == 0
    assert "⚠ Uncommitted changes" in result.output
    assert "Local branch SHA does not match remote branch SHA" in result.output
    assert "Press Enter to continue" in result.output
    assert result.output.strip().endswith(
        f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}",
    )


def test_run_path_only_outside_git_force_skips_alias_prompt(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "My Pipeline.yaml"
    yaml_file.write_text("name: demo\n")

    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        make_git_subprocess_mock(
            {("rev-parse", "--show-toplevel"): (1, "", "fatal: not a git repo")},
        ),
    )

    def fail_input() -> str:
        raise AssertionError("input should not be called when --force is set")

    monkeypatch.setattr("builtins.input", fail_input)

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=my_pipeline",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "not found"},
        status_code=404,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/my_pipeline/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["pipeline", "run", "--path", str(yaml_file), "--no-wait", "--force"],
    )

    assert result.exit_code == 0
    assert "Press Enter to accept" not in result.output
    assert "Generated alias: my_pipeline" in result.output
    assert f"Started pipeline (alias: my_pipeline), run id: {mock_pipeline_run_id}" in result.output


def test_run_path_checks_selected_repo_warnings(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    yaml_file = repo_root / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    outside_repo = tmp_path / "outside"
    outside_repo.mkdir()

    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def run_git(args, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        key = tuple(args[1:])
        if (
            key == ("rev-parse", "--show-toplevel")
            and cwd is not None
            and Path(cwd) == outside_repo
        ):
            return Result(1, "", "fatal: not a git repo")
        mapping = {
            ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
            ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
            ("status", "--porcelain"): (0, " M pipe.yaml\n", ""),
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
        }
        rc, out, err = mapping.get(key, (1, "", ""))
        return Result(rc, out, err)

    import subprocess

    monkeypatch.chdir(outside_repo)
    monkeypatch.setattr(subprocess, "run", run_git)

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "not found"},
        status_code=404,
    )
    result = runner.invoke(
        app,
        ["pipeline", "run", "--path", str(yaml_file), "--no-wait"],
        input="\n",
    )

    assert result.exit_code == 1
    assert "⚠ Uncommitted changes" in result.output
    assert "no existing pipeline was found for the provided path selector" in result.output


def test_run_api_error(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "bad"},
        status_code=400,
    )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--no-wait"])
    assert result.exit_code == 1
    assert "Run failed" in result.output


def test_run_wait_success(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    # Mock git repo to trigger no warnings
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    # Start run
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    # Polling: RUNNING -> SUCCEEDED
    httpx_mock.add_response(
        method="GET",
        url=f"https://app.getorchestra.io/api/engine/public/pipeline_runs/{mock_pipeline_run_id}/status",
        json={"runStatus": "RUNNING", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://app.getorchestra.io/api/engine/public/pipeline_runs/{mock_pipeline_run_id}/task_runs?page_size=50&page=1",
        json={
            "page": 1,
            "pageSize": 50,
            "total": 1,
            "results": [
                {
                    "id": "tr-1",
                    "taskName": "extract",
                    "status": "RUNNING",
                    "createdAt": "2026-05-29T11:29:00Z",
                },
            ],
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://app.getorchestra.io/api/engine/public/pipeline_runs/{mock_pipeline_run_id}/status",
        json={"runStatus": "SUCCEEDED", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://app.getorchestra.io/api/engine/public/pipeline_runs/{mock_pipeline_run_id}/task_runs?page_size=50&page=1",
        json={
            "page": 1,
            "pageSize": 50,
            "total": 1,
            "results": [
                {
                    "id": "tr-1",
                    "taskName": "extract",
                    "status": "SUCCEEDED",
                    "createdAt": "2026-05-29T11:29:00Z",
                    "startedAt": "2026-05-29T11:30:00Z",
                    "completedAt": "2026-05-29T11:31:30Z",
                },
            ],
        },
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--wait"])
    assert result.exit_code == 0
    assert result.output.strip().splitlines()[0] == "Starting pipeline (alias: demo)"
    assert (
        result.output.strip().splitlines()[1]
        == f"Started pipeline (alias: demo), run id: {mock_pipeline_run_id}"
    )  # noqa: E501
    assert "Invalid status value: RUNNING" not in result.output
    assert result.output.strip().splitlines()[-1] == "✅ Pipeline succeeded"


def test_run_wait_failed(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": "run-xyz"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-xyz/status",
        json={"runStatus": "RUNNING", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-xyz/task_runs?page_size=50&page=1",
        json={"page": 1, "pageSize": 50, "total": 1, "results": [{"id": "tr-1"}]},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-xyz/status",
        json={"runStatus": "FAILED", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-xyz/task_runs?page_size=50&page=1",
        json={"page": 1, "pageSize": 50, "total": 1, "results": [{"id": "tr-1"}]},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--wait"])
    assert result.exit_code == 1
    assert "Invalid status value: RUNNING" not in result.output
    assert "status FAILED" in result.output
    assert "/pipeline-runs/run-xyz/lineage" in result.output


def test_run_wait_warning(httpx_mock: HTTPXMock, monkeypatch, tmp_path: Path):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": "run-warn"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-warn/status",
        json={"runStatus": "WARNING", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-warn/task_runs?page_size=50&page=1",
        json={"page": 1, "pageSize": 50, "total": 1, "results": [{"id": "tr-1"}]},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--wait"])
    assert result.exit_code == 0
    assert result.output.strip().splitlines()[-1] == "⚠ Pipeline completed with warnings"


def test_run_git_backed_path_uses_prepared_branch_and_commit(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("status", "--porcelain", "--", "pipe.yaml"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-list", "--left-right", "--count", "@{u}...HEAD"): (0, "0 0", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("rev-parse", "HEAD"): (0, "abc123", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/pipeline-id/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"branch": "main", "commit": "abc123"},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )
    result = runner.invoke(app, ["pipeline", "run", "--path", str(yaml_file), "--no-wait"])
    assert result.exit_code == 0
    assert "Using git-backed run target branch 'main' at commit abc123" in result.output


def test_run_git_backed_path_rejects_branch_commit_overrides(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
        ("remote", "get-url", "origin"): (0, "git@github.com:org/repo.git", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("status", "--porcelain", "--", "pipe.yaml"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (0, "origin/main", ""),
        ("rev-list", "--left-right", "--count", "@{u}...HEAD"): (0, "0 0", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
        ("rev-parse", "HEAD"): (0, "abc123", ""),
    }
    import subprocess

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?repository=org%2Frepo&yaml_path=pipe.yaml",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "alias": "demo", "storage_provider": "GITHUB"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--path",
            str(yaml_file),
            "--branch",
            "override",
            "--commit",
            "deadbeef",
            "--no-wait",
        ],
    )
    assert result.exit_code == 1
    assert "--branch/-b and --commit/-c are not supported for git-backed pipelines" in result.output


def test_run_git_backed_path_rejects_branch_commit_before_git_warning_prompt(
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text("name: demo\n")
    confirm_called = False

    def fake_resolve_pipeline_selector(*_args, **_kwargs) -> PipelineSelector:
        return PipelineSelector(repository="org/repo", yaml_path="pipe.yaml")

    def fake_lookup_existing_pipeline(*_args, **_kwargs) -> dict[str, object]:
        return {"id": "pipeline-id", "storage_provider": "GITHUB"}

    def fake_confirm_git_warnings_or_exit(*_args, **_kwargs) -> None:
        nonlocal confirm_called
        confirm_called = True

    monkeypatch.setattr(
        run_pipeline_module,
        "resolve_pipeline_selector",
        fake_resolve_pipeline_selector,
    )
    monkeypatch.setattr(
        run_pipeline_module,
        "lookup_existing_pipeline",
        fake_lookup_existing_pipeline,
    )
    monkeypatch.setattr(
        run_pipeline_module,
        "confirm_git_warnings_or_exit",
        fake_confirm_git_warnings_or_exit,
    )

    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--path",
            str(yaml_file),
            "--branch",
            "override",
            "--commit",
            "deadbeef",
            "--no-wait",
        ],
    )

    assert result.exit_code == 1
    assert "--branch/-b and --commit/-c are not supported for git-backed pipelines" in result.output
    assert confirm_called is False


def test_run_generated_alias_path_skips_git_backed_prep(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    yaml_file = tmp_path / "My Pipeline.yaml"
    yaml_file.write_text("name: demo\n")

    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        make_git_subprocess_mock(
            {("rev-parse", "--show-toplevel"): (1, "", "fatal: not a git repo")},
        ),
    )

    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline?alias=my_pipeline",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"id": "pipeline-id", "alias": "my_pipeline", "storage_provider": "GITHUB"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/my_pipeline/start",
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        match_json={"branch": "override", "commit": "deadbeef"},
        json={"pipelineRunId": mock_pipeline_run_id},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "pipeline",
            "run",
            "--path",
            str(yaml_file),
            "--branch",
            "override",
            "--commit",
            "deadbeef",
            "--no-wait",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert "Using git-backed run target branch" not in result.output
    assert (
        "--branch/-b and --commit/-c are not supported for git-backed pipelines"
        not in result.output
    )
    assert f"Started pipeline (alias: my_pipeline), run id: {mock_pipeline_run_id}" in result.output


def test_run_wait_fetches_task_runs_after_pipeline_status(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    request_order: list[str] = []

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": "run-order"},
        status_code=200,
    )

    def record_status_request(request: httpx.Request) -> httpx.Response:
        request_order.append(str(request.url))
        return httpx.Response(200, json={"runStatus": "WARNING", "pipelineName": "demo"})

    def record_task_runs_request(request: httpx.Request) -> httpx.Response:
        request_order.append(str(request.url))
        return httpx.Response(
            200,
            json={"page": 1, "pageSize": 50, "total": 0, "results": []},
        )

    httpx_mock.add_callback(
        record_status_request,
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-order/status",
    )
    httpx_mock.add_callback(
        record_task_runs_request,
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-order/task_runs?page_size=50&page=1",
    )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--wait"])

    assert result.exit_code == 0
    assert request_order == [
        "https://app.getorchestra.io/api/engine/public/pipeline_runs/run-order/status",
        "https://app.getorchestra.io/api/engine/public/pipeline_runs/run-order/task_runs?page_size=50&page=1",
    ]


def test_run_wait_missing_status_retries_then_succeeds(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": "run-invalid"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-invalid/status",
        json={},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-invalid/status",
        json={"runStatus": "SUCCEEDED", "pipelineName": "demo"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-invalid/task_runs?page_size=50&page=1",
        json={"page": 1, "pageSize": 50, "total": 0, "results": []},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--wait"])

    assert result.exit_code == 0
    assert "Invalid status value: None" not in result.output
    assert result.output.strip().splitlines()[-1] == "✅ Pipeline succeeded"


def test_run_wait_missing_status_exits_after_retry_limit(
    httpx_mock: HTTPXMock,
    monkeypatch,
    tmp_path: Path,
):
    repo_root = tmp_path
    mapping = {
        ("rev-parse", "--show-toplevel"): (0, str(repo_root), ""),
        ("status", "--porcelain"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", ""),
    }
    import subprocess
    import time

    monkeypatch.setattr(subprocess, "run", make_git_subprocess_mock(mapping))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/demo/start",
        json={"pipelineRunId": "run-missing"},
        status_code=200,
    )
    for _ in range(4):
        httpx_mock.add_response(
            method="GET",
            url="https://app.getorchestra.io/api/engine/public/pipeline_runs/run-missing/status",
            json={},
            status_code=200,
        )

    result = runner.invoke(app, ["pipeline", "run", "--alias", "demo", "--wait"])

    assert result.exit_code == 1
    assert "Invalid status value: None" in result.output
