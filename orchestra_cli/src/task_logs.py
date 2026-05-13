import codecs
import re
import sys
import time
from collections.abc import Iterable

import click
import httpx
import typer

from ..utils.api import auth_headers, fail_with_response, request_or_exit, require_api_key
from ..utils.constants import get_api_url
from ..utils.styling import bold, indent_message, red, yellow

POLL_INTERVAL_SECONDS = 2
CONTENT_RANGE_RE = re.compile(r"^bytes (?P<start>\d+)-(?P<end>\d+)/(?P<total>\d+|\*)$")
CONTENT_RANGE_EOF_RE = re.compile(r"^bytes \*/(?P<total>\d+|\*)$")


def _success_json_or_exit(response: httpx.Response, action: str) -> object:
    try:
        return response.json()
    except Exception:
        typer.echo(red(f"❌ {action} failed: success response was not valid JSON"))
        typer.echo(yellow(indent_message(response.text)))
        raise typer.Exit(code=1)


def _resolve_pipeline_run_id(task_run_id: str, api_key: str) -> str:
    response = request_or_exit(
        httpx.get,
        get_api_url("task_runs"),
        params={"task_run_ids": task_run_id},
        timeout=30,
        headers=auth_headers(api_key),
    )
    if response.status_code != 200:
        raise fail_with_response("Resolve task run", response)

    body = _success_json_or_exit(response, "Resolve task run")
    results = body.get("results") if isinstance(body, dict) else body
    if not isinstance(results, list) or not results:
        typer.echo(red(f"❌ No task run found for id {task_run_id}"))
        raise typer.Exit(code=1)

    matching_task_runs = [
        task_run
        for task_run in results
        if isinstance(task_run, dict) and task_run.get("id") == task_run_id
    ]
    task_run = matching_task_runs[0] if matching_task_runs else results[0]
    if not isinstance(task_run, dict):
        typer.echo(red("❌ Resolve task run failed: response did not include task run details"))
        raise typer.Exit(code=1)

    pipeline_run_id = task_run.get("pipelineRunId")
    if not isinstance(pipeline_run_id, str) or not pipeline_run_id:
        typer.echo(red("❌ Resolve task run failed: response did not include pipelineRunId"))
        raise typer.Exit(code=1)

    return pipeline_run_id


def _task_logs_url(pipeline_run_id: str, task_run_id: str) -> str:
    return get_api_url(f"pipeline_runs/{pipeline_run_id}/task_runs/{task_run_id}/logs")


def _download_log_url(pipeline_run_id: str, task_run_id: str) -> str:
    return f"{_task_logs_url(pipeline_run_id, task_run_id)}/download"


def _list_log_filenames(pipeline_run_id: str, task_run_id: str, api_key: str) -> list[str]:
    response = request_or_exit(
        httpx.get,
        _task_logs_url(pipeline_run_id, task_run_id),
        timeout=30,
        headers=auth_headers(api_key),
    )
    if response.status_code != 200:
        raise fail_with_response("List task logs", response)

    body = _success_json_or_exit(response, "List task logs")
    filenames = body.get("filenames") if isinstance(body, dict) else None
    if not isinstance(filenames, list) or not all(isinstance(name, str) for name in filenames):
        typer.echo(red("❌ List task logs failed: response did not include filenames"))
        raise typer.Exit(code=1)
    if not filenames:
        typer.echo(yellow(f"No log files found for task run {task_run_id}"))
        raise typer.Exit(code=0)
    return filenames


def _render_filename_options(filenames: Iterable[str], selected_index: int) -> None:
    for index, filename in enumerate(filenames):
        marker = ">" if index == selected_index else " "
        typer.echo(f"{marker} {filename}\033[K")


def _select_filename_with_arrow_keys(filenames: list[str]) -> str:
    selected_index = 0
    typer.echo(bold("Select a log file (↑/↓ to move, Enter to select):"))
    _render_filename_options(filenames, selected_index)

    while True:
        char = click.getchar()
        if char == "\x03":
            raise KeyboardInterrupt
        if char in {"\r", "\n"}:
            return filenames[selected_index]

        sequence = char
        if char == "\x1b":
            sequence += click.getchar()
            sequence += click.getchar()

        if sequence in {"\x1b[A", "k"}:
            selected_index = (selected_index - 1) % len(filenames)
        elif sequence in {"\x1b[B", "j"}:
            selected_index = (selected_index + 1) % len(filenames)
        else:
            continue

        typer.echo(f"\033[{len(filenames)}A", nl=False)
        _render_filename_options(filenames, selected_index)


def _select_filename_with_prompt(filenames: list[str]) -> str:
    for index, filename in enumerate(filenames, start=1):
        typer.echo(f"{index}. {filename}")

    while True:
        raw_choice = typer.prompt("Select log file", default="1")
        try:
            choice = int(raw_choice)
        except ValueError:
            typer.echo(red("Please enter a number from the list"))
            continue

        if 1 <= choice <= len(filenames):
            return filenames[choice - 1]

        typer.echo(red("Please enter a number from the list"))


def _select_filename(filenames: list[str]) -> str:
    if len(filenames) == 1:
        return filenames[0]
    if sys.stdin.isatty():
        return _select_filename_with_arrow_keys(filenames)
    return _select_filename_with_prompt(filenames)


def _parse_content_range(response: httpx.Response) -> tuple[int | None, int | None]:
    content_range = response.headers.get("content-range")
    if not content_range:
        return None, None

    match = CONTENT_RANGE_RE.match(content_range)
    if match:
        total_text = match.group("total")
        total_size = None if total_text == "*" else int(total_text)
        return int(match.group("end")) + 1, total_size

    match = CONTENT_RANGE_EOF_RE.match(content_range)
    if match:
        total_text = match.group("total")
        total_size = None if total_text == "*" else int(total_text)
        return None, total_size

    return None, None


def _file_status(response: httpx.Response) -> str | None:
    raw_status = response.headers.get("x-file-status")
    if not raw_status:
        return None
    return raw_status.strip().upper()


def _response_content_and_offset(response: httpx.Response, offset: int) -> tuple[bytes, int]:
    content = response.content
    next_offset, _ = _parse_content_range(response)
    if response.status_code == 200 and offset > 0:
        if len(content) <= offset:
            return b"", next_offset if next_offset is not None else len(content)
        return content[offset:], next_offset if next_offset is not None else len(content)
    return content, next_offset if next_offset is not None else offset + len(content)


def _is_eof_response(response: httpx.Response) -> bool:
    if response.status_code == 204:
        return True
    if response.status_code != 500:
        return False

    try:
        detail = response.json().get("detail")
    except Exception:
        return False
    return detail == "Failed to download log file from S3"


def _follow_log_file(
    pipeline_run_id: str,
    task_run_id: str,
    filename: str,
    api_key: str,
) -> None:
    offset = 0
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    latest_file_status: str | None = None

    try:
        while True:
            headers = {**auth_headers(api_key), "Range": f"bytes={offset}-"}
            response = request_or_exit(
                httpx.get,
                _download_log_url(pipeline_run_id, task_run_id),
                params={"filename": filename},
                timeout=30,
                headers=headers,
            )

            if response.status_code in {200, 206}:
                latest_file_status = _file_status(response) or latest_file_status
                new_content, offset = _response_content_and_offset(response, offset)
                text = decoder.decode(new_content)
                if text:
                    typer.echo(text, nl=False)
                _, total_size = _parse_content_range(response)
                if (
                    latest_file_status == "READY"
                    and total_size is not None
                    and offset >= total_size
                ):
                    break
            elif response.status_code == 416:
                latest_file_status = _file_status(response) or latest_file_status
                _, total_size = _parse_content_range(response)
                if latest_file_status == "READY" and (total_size is None or offset >= total_size):
                    break
                if offset == 0:
                    raise fail_with_response("Download task log", response)
            elif offset > 0 and _is_eof_response(response):
                break
            else:
                raise fail_with_response("Download task log", response)

            time.sleep(POLL_INTERVAL_SECONDS)
        remaining_text = decoder.decode(b"", final=True)
        if remaining_text:
            typer.echo(remaining_text, nl=False)
    except KeyboardInterrupt:
        remaining_text = decoder.decode(b"", final=True)
        if remaining_text:
            typer.echo(remaining_text, nl=False)
        typer.echo(yellow("\nStopped following logs"), err=True)


def task_logs(
    task_run_id: str = typer.Option(
        ...,
        "--task-run-id",
        "-tr",
        help="Task run ID to fetch logs for",
    ),
    filename: str | None = typer.Option(
        None,
        "--filename",
        "-f",
        help="Specific log filename to fetch",
    ),
):
    """
    Follow logs for a single Orchestra task run.
    """
    api_key = require_api_key()
    pipeline_run_id = _resolve_pipeline_run_id(task_run_id, api_key)
    selected_filename = filename
    if not selected_filename:
        selected_filename = _select_filename(
            _list_log_filenames(pipeline_run_id, task_run_id, api_key),
        )

    _follow_log_file(
        pipeline_run_id=pipeline_run_id,
        task_run_id=task_run_id,
        filename=selected_filename,
        api_key=api_key,
    )
