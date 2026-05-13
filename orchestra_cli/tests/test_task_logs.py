import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

import orchestra_cli.src.task_logs as task_logs_module
from orchestra_cli.src.cli import app

runner = CliRunner()
mock_api_key = "fake-key"
mock_task_run_id = "3d68b5dc-54eb-43db-8294-4734d032ff92"
mock_pipeline_run_id = "d4159d06-4366-4fd7-b74e-d30b4a10565a"


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_API_KEY", mock_api_key)
    monkeypatch.setenv("BASE_URL", "")


def _mock_task_run_lookup(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public/task_runs"
            f"?task_run_ids={mock_task_run_id}"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={
            "results": [
                {
                    "id": mock_task_run_id,
                    "pipelineRunId": mock_pipeline_run_id,
                },
            ],
        },
        status_code=200,
    )


def test_task_logs_with_filename_follows_until_ready(httpx_mock: HTTPXMock, monkeypatch):
    _mock_task_run_lookup(httpx_mock)
    monkeypatch.setattr(task_logs_module.time, "sleep", lambda _: None)
    download_url = (
        "https://app.getorchestra.io/api/engine/public"
        f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
        "/logs/download?filename=main.log"
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello\n",
        headers={"content-range": "bytes 0-5/12", "x-file-status": "WRITING"},
        status_code=206,
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=6-"},
        content=b"world\n",
        headers={"content-range": "bytes 6-11/12", "x-file-status": "READY"},
        status_code=206,
    )

    result = runner.invoke(
        app,
        ["task", "logs", "--task-run-id", mock_task_run_id, "--filename", "main.log"],
    )

    assert result.exit_code == 0
    assert "hello\nworld\n" in result.output


def test_task_logs_completed_file_exits_on_non_pending_status_response(httpx_mock: HTTPXMock):
    _mock_task_run_lookup(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
            "/logs/download?filename=main.log"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello\n",
        headers={"content-range": "bytes 0-5/6", "x-file-status": "COMPLETE"},
        status_code=200,
    )

    result = runner.invoke(app, ["task", "logs", "-tr", mock_task_run_id, "-f", "main.log"])

    assert result.exit_code == 0
    assert result.output == "hello\n"


def test_task_logs_no_follow_reads_current_content_once(httpx_mock: HTTPXMock):
    _mock_task_run_lookup(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
            "/logs/download?filename=main.log"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello\n",
        headers={"content-range": "bytes 0-5/12", "x-file-status": "PENDING"},
        status_code=206,
    )

    result = runner.invoke(
        app,
        ["task", "logs", "-tr", mock_task_run_id, "-f", "main.log", "--no-follow"],
    )

    assert result.exit_code == 0
    assert result.output == "hello\n"


def test_task_logs_flushes_decoder_on_normal_completion(httpx_mock: HTTPXMock):
    _mock_task_run_lookup(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
            "/logs/download?filename=main.log"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello \xe2",
        headers={"content-range": "bytes 0-6/7", "x-file-status": "READY"},
        status_code=200,
    )

    result = runner.invoke(app, ["task", "logs", "-tr", mock_task_run_id, "-f", "main.log"])

    assert result.exit_code == 0
    assert result.output == "hello \ufffd"


def test_task_logs_treats_post_content_s3_error_as_eof(httpx_mock: HTTPXMock, monkeypatch):
    _mock_task_run_lookup(httpx_mock)
    monkeypatch.setattr(task_logs_module.time, "sleep", lambda _: None)
    download_url = (
        "https://app.getorchestra.io/api/engine/public"
        f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
        "/logs/download?filename=main.log"
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello\n",
        status_code=206,
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=6-"},
        json={"detail": "Failed to download log file from S3"},
        status_code=500,
    )

    result = runner.invoke(
        app,
        ["task", "logs", "--task-run-id", mock_task_run_id, "--filename", "main.log"],
    )

    assert result.exit_code == 0
    assert "hello\n" in result.output
    assert "Download task log failed" not in result.output


def test_task_logs_416_while_writing_keeps_polling(httpx_mock: HTTPXMock, monkeypatch):
    _mock_task_run_lookup(httpx_mock)
    monkeypatch.setattr(task_logs_module.time, "sleep", lambda _: None)
    download_url = (
        "https://app.getorchestra.io/api/engine/public"
        f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
        "/logs/download?filename=main.log"
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello\n",
        headers={"content-range": "bytes 0-5/12", "x-file-status": "WRITING"},
        status_code=206,
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=6-"},
        headers={"content-range": "bytes */12", "x-file-status": "WRITING"},
        status_code=416,
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=6-"},
        content=b"world\n",
        headers={"content-range": "bytes 6-11/12", "x-file-status": "READY"},
        status_code=206,
    )

    result = runner.invoke(
        app,
        ["task", "logs", "--task-run-id", mock_task_run_id, "--filename", "main.log"],
    )

    assert result.exit_code == 0
    assert "hello\nworld\n" in result.output
    assert "Download task log failed" not in result.output


def test_task_logs_full_range_while_writing_keeps_polling(httpx_mock: HTTPXMock, monkeypatch):
    _mock_task_run_lookup(httpx_mock)
    monkeypatch.setattr(task_logs_module.time, "sleep", lambda _: None)
    download_url = (
        "https://app.getorchestra.io/api/engine/public"
        f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
        "/logs/download?filename=main.log"
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello\n",
        headers={"content-range": "bytes 0-5/6", "x-file-status": "WRITING"},
        status_code=206,
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=6-"},
        content=b"world\n",
        headers={"content-range": "bytes 6-11/12", "x-file-status": "READY"},
        status_code=206,
    )

    result = runner.invoke(
        app,
        ["task", "logs", "--task-run-id", mock_task_run_id, "--filename", "main.log"],
    )

    assert result.exit_code == 0
    assert "hello\nworld\n" in result.output


def test_task_logs_missing_status_uses_known_total_size(httpx_mock: HTTPXMock, monkeypatch):
    _mock_task_run_lookup(httpx_mock)
    monkeypatch.setattr(task_logs_module.time, "sleep", lambda _: None)
    download_url = (
        "https://app.getorchestra.io/api/engine/public"
        f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
        "/logs/download?filename=main.log"
    )
    httpx_mock.add_response(
        method="GET",
        url=download_url,
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"hello\n",
        headers={"content-range": "bytes 0-5/6"},
        status_code=200,
    )

    result = runner.invoke(app, ["task", "logs", "-tr", mock_task_run_id, "-f", "main.log"])

    assert result.exit_code == 0
    assert result.output == "hello\n"


def test_task_logs_initial_s3_error_still_fails(httpx_mock: HTTPXMock):
    _mock_task_run_lookup(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
            "/logs/download?filename=main.log"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        json={"detail": "Failed to download log file from S3"},
        status_code=500,
    )

    result = runner.invoke(app, ["task", "logs", "-tr", mock_task_run_id, "-f", "main.log"])

    assert result.exit_code == 1
    assert "Download task log failed" in result.output


def test_task_logs_without_filename_prompts_for_log_file(httpx_mock: HTTPXMock):
    _mock_task_run_lookup(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}/logs"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"filenames": ["debug.log", "main.log"]},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
            "/logs/download?filename=main.log"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"selected log\n",
        headers={"content-range": "bytes 0-12/13", "x-file-status": "READY"},
        status_code=200,
    )

    result = runner.invoke(app, ["task", "logs", "-tr", mock_task_run_id], input="2\n")

    assert result.exit_code == 0
    assert "1. debug.log" in result.output
    assert "2. main.log" in result.output
    assert "selected log\n" in result.output


def test_task_logs_empty_filename_prompts_for_log_file(httpx_mock: HTTPXMock):
    _mock_task_run_lookup(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}/logs"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"filenames": ["debug.log", "main.log"]},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}"
            "/logs/download?filename=main.log"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}", "Range": "bytes=0-"},
        content=b"selected log\n",
        headers={"content-range": "bytes 0-12/13", "x-file-status": "READY"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        ["task", "logs", "-tr", mock_task_run_id, "-f", ""],
        input="2\n",
    )

    assert result.exit_code == 0
    assert "1. debug.log" in result.output
    assert "2. main.log" in result.output
    assert "selected log\n" in result.output


def test_task_logs_no_available_files_exits_cleanly(httpx_mock: HTTPXMock):
    _mock_task_run_lookup(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public"
            f"/pipeline_runs/{mock_pipeline_run_id}/task_runs/{mock_task_run_id}/logs"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"filenames": []},
        status_code=200,
    )

    result = runner.invoke(app, ["task", "logs", "-tr", mock_task_run_id], input="1\n")

    assert result.exit_code == 0
    assert f"No log files found for task run {mock_task_run_id}" in result.output


def test_task_logs_resolve_task_run_api_error(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://app.getorchestra.io/api/engine/public/task_runs"
            f"?task_run_ids={mock_task_run_id}"
        ),
        match_headers={"Authorization": f"Bearer {mock_api_key}"},
        json={"detail": "not found"},
        status_code=404,
    )

    result = runner.invoke(app, ["task", "logs", "-tr", mock_task_run_id, "-f", "main.log"])

    assert result.exit_code == 1
    assert "Resolve task run failed" in result.output
