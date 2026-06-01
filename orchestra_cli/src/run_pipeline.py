import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from ..utils.api import auth_headers, fail_with_response, request_or_exit, require_api_key
from ..utils.constants import get_api_url, get_base_url
from ..utils.git import GitAction, confirm_git_warnings_or_exit, prepare_git_backed_run_target
from ..utils.pipeline_selector import (
    PipelineSelector,
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.pipeline_update import build_update_selector, storage_provider
from ..utils.styling import bold, green, indent_message, red, yellow
from ..utils.yaml_loader import load_validated_pipeline_data

STATUS_STYLES = {
    "CREATED": "cyan",
    "QUEUED": "yellow",
    "RUNNING": "blue",
    "SUCCEEDED": "green",
    "WARNING": "yellow",
    "SKIPPED": "yellow",
    "FAILED": "red",
    "CANCELLED": "red",
}
IN_PROGRESS_RUN_STATUSES = {"RUNNING", "QUEUED", "CREATED"}
TERMINAL_RUN_STATUSES = {"SUCCEEDED", "WARNING", "SKIPPED", "FAILED", "CANCELLED"}


def _lookup_existing_pipeline(selector: PipelineSelector, api_key: str) -> dict[str, object] | None:
    response = request_or_exit(
        httpx.get,
        get_api_url("pipeline"),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise fail_with_response("Run", response)
    try:
        body = response.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        typer.echo(red("❌ Run failed: pipeline lookup response was not a JSON object"))
        raise typer.Exit(code=1)
    return body


def _parse_key_value_pairs(values: list[str], option_name: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in values:
        key, sep, value = raw.partition("=")
        key = key.strip()
        if sep != "=" or not key:
            typer.echo(red(f"❌ Invalid {option_name} value '{raw}'. Expected KEY=VAL"))
            raise typer.Exit(code=1)
        parsed[key] = value
    return parsed


def _typed_environment_override(value: str) -> dict[str, str | int | bool]:
    lowered = value.strip().lower()
    if lowered == "true":
        return {"type": "bool", "value": True}
    if lowered == "false":
        return {"type": "bool", "value": False}
    if value.strip().isdigit() or (value.strip().startswith("-") and value.strip()[1:].isdigit()):
        return {"type": "int", "value": int(value.strip())}
    return {"type": "string", "value": value}


def _build_environment_overrides(values: list[str]) -> dict[str, dict[str, str | int | bool]]:
    parsed = _parse_key_value_pairs(values, "-e/--env")
    return {key: _typed_environment_override(value) for key, value in parsed.items()}


def _resolve_environment_value(
    environment_id: str | None,
    environment_name: str | None,
) -> str | None:
    if environment_id and environment_name:
        typer.echo(red("❌ Provide only one of --environment-id or --environment-name"))
        raise typer.Exit(code=1)
    return environment_id or environment_name


def _task_lookup_entries(
    pipeline_data: dict[str, object],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    pipeline_root = pipeline_data.get("pipeline")
    if not isinstance(pipeline_root, dict):
        typer.echo(red("❌ Run failed: YAML does not include a valid top-level 'pipeline' object"))
        raise typer.Exit(code=1)

    task_entries: dict[str, str] = {}
    group_entries: dict[str, list[str]] = {}
    for group_id, group_body in pipeline_root.items():
        if not isinstance(group_id, str) or not isinstance(group_body, dict):
            continue
        tasks_body = group_body.get("tasks")
        if not isinstance(tasks_body, dict):
            continue

        group_task_ids: list[str] = []
        for task_id, task_body in tasks_body.items():
            if not isinstance(task_id, str):
                continue
            group_task_ids.append(task_id)
            task_entries[task_id] = task_id
            if isinstance(task_body, dict):
                task_name = task_body.get("name")
                if isinstance(task_name, str) and task_name.strip():
                    task_entries.setdefault(task_name.strip(), task_id)

        if not group_task_ids:
            continue
        group_entries[group_id] = group_task_ids
        group_name = group_body.get("name")
        if isinstance(group_name, str) and group_name.strip():
            group_entries.setdefault(group_name.strip(), group_task_ids)
    return task_entries, group_entries


def _resolve_task_ids(task: str, path: Path | None) -> list[str]:
    if path is None:
        return [task]

    pipeline_data = load_validated_pipeline_data(path)
    task_entries, group_entries = _task_lookup_entries(pipeline_data)
    if task in task_entries:
        return [task_entries[task]]
    if task in group_entries:
        return group_entries[task]

    typer.echo(
        red(
            f"❌ Could not resolve --task '{task}' from YAML at {path}. "
            "Use a task ID, task name, task-group ID, or task-group name.",
        ),
    )
    raise typer.Exit(code=1)


def _parse_task_runs_response(response: httpx.Response) -> list[dict[str, object]]:
    try:
        body = response.json()
    except Exception:
        return []
    if isinstance(body, dict):
        results = body.get("results")
        if isinstance(results, list):
            return [entry for entry in results if isinstance(entry, dict)]
    if isinstance(body, list):
        return [entry for entry in body if isinstance(entry, dict)]
    return []


def _poll_all_task_runs(
    *,
    pipeline_run_id: str,
    api_key: str,
) -> list[dict[str, object]]:
    headers = auth_headers(api_key)
    task_runs: list[dict[str, object]] = []
    page = 1
    while True:
        response = request_or_exit(
            httpx.get,
            get_api_url(f"pipeline_runs/{pipeline_run_id}/task_runs"),
            params={"page_size": 50, "page": page},
            timeout=30,
            headers=headers,
        )
        if not (200 <= response.status_code < 300):
            typer.echo(red(f"❌ Task run polling failed with HTTP {response.status_code}"))
            raise typer.Exit(code=1)

        page_results = _parse_task_runs_response(response)
        task_runs.extend(page_results)

        try:
            body = response.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            break
        total = body.get("total")
        if isinstance(total, int) and len(task_runs) < total and page_results:
            page += 1
            continue
        break
    return task_runs


def _parse_created_at_utc(status_body: dict[str, object]) -> datetime | None:
    created_at_candidates = [status_body.get("createdAt")]
    candidate_containers = [
        status_body.get("pipelineRun"),
        status_body.get("result"),
        status_body.get("data"),
    ]
    for container in candidate_containers:
        if isinstance(container, dict):
            created_at_candidates.append(container.get("createdAt"))

    for candidate in created_at_candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        normalized_candidate = candidate.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized_candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _parse_iso_datetime_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized_value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_pipeline_duration(created_at_utc: datetime, now_utc: datetime | None = None) -> str:
    comparison_time = now_utc or datetime.now().astimezone(UTC)
    elapsed_seconds = max(0, int((comparison_time - created_at_utc).total_seconds()))
    hours, remainder = divmod(elapsed_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        unit = "hour" if hours == 1 else "hours"
        return f"{hours}:{minutes:02d}:{seconds:02d} {unit}"
    if minutes > 0:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes}:{seconds:02d} {unit}"
    unit = "second" if seconds == 1 else "seconds"
    return f"{seconds} {unit}"


def _build_poll_status_text(
    status_value: str,
    created_at_utc: datetime | None = None,
    now_utc: datetime | None = None,
) -> Text:
    text = Text("Pipeline status: ")
    text.append(status_value, style=f"bold {STATUS_STYLES.get(status_value, 'white')}")
    if created_at_utc is not None:
        text.append(f" ({_format_pipeline_duration(created_at_utc, now_utc)})", style="dim")
    return text


def _build_live_status_text(seconds_since_check: int) -> Text:
    unit = "second" if seconds_since_check == 1 else "seconds"
    text = Text("Live status ", style="dim")
    text.append(f"(updated {seconds_since_check} {unit} ago)", style="dim")
    return text


def _task_run_name(task_run: dict[str, object]) -> str:
    for key in ("taskName", "taskId", "id"):
        value = task_run.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "Unknown task"


def _task_run_id(task_run: dict[str, object]) -> str:
    task_run_id = task_run.get("id")
    if isinstance(task_run_id, str) and task_run_id.strip():
        return task_run_id
    return "-"


def _task_run_message(task_run: dict[str, object]) -> str:
    for key in ("message", "externalMessage"):
        value = task_run.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "-"


def _task_run_sort_key(task_run: dict[str, object]) -> tuple[bool, datetime, str]:
    created_at = _parse_iso_datetime_utc(task_run.get("createdAt"))
    return (
        created_at is None,
        created_at or datetime.max.replace(tzinfo=UTC),
        _task_run_name(task_run).lower(),
    )


def _format_task_run_timing(task_run: dict[str, object], now_utc: datetime | None = None) -> str:
    created_at = _parse_iso_datetime_utc(task_run.get("createdAt"))
    started_at = _parse_iso_datetime_utc(task_run.get("startedAt"))
    completed_at = _parse_iso_datetime_utc(task_run.get("completedAt"))

    if started_at is not None and completed_at is not None:
        return f"ran for {_format_pipeline_duration(started_at, completed_at)}"
    if started_at is not None:
        return f"running for {_format_pipeline_duration(started_at, now_utc)}"
    if completed_at is not None and created_at is not None:
        return f"finished in {_format_pipeline_duration(created_at, completed_at)}"
    if created_at is not None:
        return f"pending for {_format_pipeline_duration(created_at, now_utc)}"
    return "timing unavailable"


def _build_task_runs_table(
    task_runs: list[dict[str, object]],
    *,
    can_fetch_task_runs: bool,
    now_utc: datetime | None = None,
) -> Table | Text:
    if not can_fetch_task_runs:
        return Text("Task runs: waiting for pipeline run to be created", style="dim")
    if not task_runs:
        return Text("Task runs: none yet", style="dim")

    table = Table(title="Task runs", box=None, pad_edge=False, show_edge=False)
    table.add_column("Task", overflow="fold")
    table.add_column("Task run ID", overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Timing", overflow="fold")
    table.add_column("Message", overflow="fold")

    for task_run in sorted(task_runs, key=_task_run_sort_key):
        status_value = task_run.get("status")
        status_text = Text(str(status_value or "UNKNOWN"))
        if isinstance(status_value, str):
            status_text = Text(
                status_value,
                style=f"bold {STATUS_STYLES.get(status_value, 'white')}",
            )
        table.add_row(
            _task_run_name(task_run),
            _task_run_id(task_run),
            status_text,
            _format_task_run_timing(task_run, now_utc),
            _task_run_message(task_run),
        )

    return table


def _build_poll_display(
    *,
    status_value: str,
    seconds_since_check: int,
    created_at_utc: datetime | None,
    task_runs: list[dict[str, object]],
    can_fetch_task_runs: bool,
    now_utc: datetime | None = None,
) -> Group:
    return Group(
        _build_live_status_text(seconds_since_check),
        _build_poll_status_text(status_value, created_at_utc, now_utc),
        _build_task_runs_table(
            task_runs,
            can_fetch_task_runs=can_fetch_task_runs,
            now_utc=now_utc,
        ),
    )


def _create_poll_status_display() -> Live | None:
    console = Console()
    if not console.is_terminal:
        return None
    live = Live(console=console, refresh_per_second=4, transient=False)
    live.start()
    return live


def _stop_poll_status_display(poll_status_display: Live | None) -> None:
    if poll_status_display is not None:
        poll_status_display.stop()


def _sleep_with_status_updates(
    *,
    poll_interval_seconds: int,
    poll_status_display: Live | None,
    status_value: str | None,
    created_at_utc: datetime | None,
    task_runs: list[dict[str, object]],
    can_fetch_task_runs: bool,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    if poll_status_display is None or status_value is None:
        sleep_fn(poll_interval_seconds)
        return

    for seconds_since_check in range(1, poll_interval_seconds + 1):
        sleep_fn(1)
        poll_status_display.update(
            _build_poll_display(
                status_value=status_value,
                seconds_since_check=seconds_since_check,
                created_at_utc=created_at_utc,
                task_runs=task_runs,
                can_fetch_task_runs=can_fetch_task_runs,
            ),
        )


def _poll_until_terminal(
    *,
    selector_name: str,
    pipeline_run_id: str,
    api_key: str,
    lineage_url: str,
    created_at_utc: datetime | None = None,
) -> None:
    """Poll the run status endpoint until the run reaches a terminal state."""
    poll_interval_seconds = 5
    headers = auth_headers(api_key)
    status_url = get_api_url(f"pipeline_runs/{pipeline_run_id}/status")
    poll_status_display = _create_poll_status_display()
    last_status_value: str | None = None
    last_task_runs: list[dict[str, object]] = []
    can_fetch_task_runs = False

    try:
        while True:
            _sleep_with_status_updates(
                poll_interval_seconds=poll_interval_seconds,
                poll_status_display=poll_status_display,
                status_value=last_status_value,
                created_at_utc=created_at_utc,
                task_runs=last_task_runs,
                can_fetch_task_runs=can_fetch_task_runs,
            )
            try:
                status_resp = httpx.get(status_url, headers=headers, timeout=30)
            except Exception as exc:
                _stop_poll_status_display(poll_status_display)
                poll_status_display = None
                typer.echo(yellow(f"Polling request failed: {exc}"))
                continue

            if not (200 <= status_resp.status_code < 300):
                _stop_poll_status_display(poll_status_display)
                poll_status_display = None
                typer.echo(red(f"❌ Status check failed with HTTP {status_resp.status_code}"))
                try:
                    typer.echo(yellow(indent_message(status_resp.text)))
                except Exception:
                    pass
                raise typer.Exit(code=1)

            try:
                status_body = status_resp.json()
            except Exception:
                status_body = {}

            status_value = status_body.get("runStatus")
            created_at_utc = created_at_utc or _parse_created_at_utc(status_body)

            if isinstance(status_value, str):
                last_status_value = status_value
                can_fetch_task_runs = status_value in (
                    IN_PROGRESS_RUN_STATUSES | TERMINAL_RUN_STATUSES
                )
                if can_fetch_task_runs:
                    last_task_runs = _poll_all_task_runs(
                        pipeline_run_id=pipeline_run_id,
                        api_key=api_key,
                    )
                if poll_status_display is not None:
                    poll_status_display.update(
                        _build_poll_display(
                            status_value=status_value,
                            seconds_since_check=0,
                            created_at_utc=created_at_utc,
                            task_runs=last_task_runs,
                            can_fetch_task_runs=can_fetch_task_runs,
                        ),
                    )
                else:
                    typer.echo(f"Pipeline ({selector_name}) status: {status_value}")

            if status_value == "SUCCEEDED":
                _stop_poll_status_display(poll_status_display)
                poll_status_display = None
                typer.echo(green("✅ Pipeline succeeded"))
                raise typer.Exit(code=0)

            if status_value == "WARNING":
                _stop_poll_status_display(poll_status_display)
                poll_status_display = None
                typer.echo(yellow("⚠ Pipeline completed with warnings"))
                raise typer.Exit(code=0)

            if status_value == "SKIPPED":
                _stop_poll_status_display(poll_status_display)
                poll_status_display = None
                typer.echo(yellow("⚠ Pipeline skipped"))
                raise typer.Exit(code=0)

            if status_value in {"FAILED", "CANCELLED"}:
                _stop_poll_status_display(poll_status_display)
                poll_status_display = None
                typer.echo(
                    red(
                        f"❌ Pipeline ended with status {status_value}. See lineage for details.",
                    ),
                )
                typer.echo(yellow(lineage_url))
                raise typer.Exit(code=1)

            if status_value in IN_PROGRESS_RUN_STATUSES:
                continue

            _stop_poll_status_display(poll_status_display)
            poll_status_display = None
            typer.echo(
                red(f"❌ Invalid status value: {status_value}\nResponse body: {status_body}"),
            )
    finally:
        _stop_poll_status_display(poll_status_display)


def build_run_payload(
    branch: str | None = None,
    commit: str | None = None,
    version_number: int | None = None,
    environment: str | None = None,
    run_inputs: dict[str, str] | None = None,
    environment_overrides: dict[str, dict[str, str | int | bool]] | None = None,
    task_ids: list[str] | None = None,
    continue_downstream_run: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if branch:
        payload["branch"] = branch
    if commit:
        payload["commit"] = commit
    if version_number is not None:
        payload["versionNumber"] = version_number
    if environment:
        payload["environment"] = environment
    if run_inputs:
        payload["runInputs"] = run_inputs
    if environment_overrides:
        payload["environmentOverrides"] = environment_overrides
    if task_ids:
        payload["taskIds"] = task_ids
    if continue_downstream_run is not None:
        payload["continueDownstreamRun"] = continue_downstream_run
    return payload


def _resolve_start_path(
    selector: PipelineSelector,
    existing_pipeline: dict[str, object] | None = None,
) -> str:
    pipeline_identifier = selector.alias or selector.pipeline_id
    if pipeline_identifier:
        return f"pipelines/{pipeline_identifier}/start"

    if existing_pipeline is not None:
        existing_pipeline_id = existing_pipeline.get("id")
        if isinstance(existing_pipeline_id, str) and existing_pipeline_id.strip():
            return f"pipelines/{existing_pipeline_id}/start"
        typer.echo(red("❌ Run failed: failed to load pipeline id"))
        raise typer.Exit(code=1)

    return "pipelines/start"


def start_pipeline_run(
    selector: PipelineSelector,
    api_key: str,
    payload: dict[str, Any] | None,
    wait: bool,
    failure_action: str,
    existing_pipeline: dict[str, object] | None = None,
) -> None:
    selector_name = selector.display()
    start_path = _resolve_start_path(selector, existing_pipeline)

    typer.echo(f"Starting pipeline ({selector_name})")
    response = request_or_exit(
        httpx.post,
        get_api_url(start_path),
        json=payload if payload is not None else None,
        timeout=30,
        headers=auth_headers(api_key),
    )

    if 200 <= response.status_code < 300:
        try:
            body = response.json()
        except Exception:
            body = {}
        created_at_utc = _parse_created_at_utc(body)

        pipeline_run_id = body.get("pipelineRunId")

        if not pipeline_run_id:
            typer.echo(
                yellow(
                    f"Started pipeline ({selector_name}), "
                    "but could not determine run id from response",
                ),
            )
            raise typer.Exit(code=0)

        if not wait:
            typer.echo(f"Started pipeline ({selector_name}), run id: {str(pipeline_run_id)}")
            raise typer.Exit(code=0)

        lineage_url = f"{get_base_url()}/pipeline-runs/{pipeline_run_id}/lineage"

        typer.echo(green(f"Started pipeline ({selector_name}), run id: {pipeline_run_id}"))
        typer.echo(yellow(f"Lineage: {lineage_url}"))
        typer.echo(bold("Polling pipeline status... (Ctrl+C to stop)"))

        _poll_until_terminal(
            selector_name=selector_name,
            pipeline_run_id=str(pipeline_run_id),
            api_key=api_key,
            lineage_url=lineage_url,
            created_at_utc=created_at_utc,
        )
        return

    raise fail_with_response(failure_action, response)


def run_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Git branch name"),
    commit: str | None = typer.Option(None, "--commit", "-c", help="Commit SHA"),
    version_number: int | None = typer.Option(
        None,
        "--version-number",
        "--version",
        help="Pipeline version number (Orchestra-backed pipelines)",
    ),
    task: str | None = typer.Option(
        None,
        "--task",
        "-t",
        help="Task ID, task name, task-group ID, or task-group name",
    ),
    continue_downstream_run: bool = typer.Option(
        False,
        "--continue",
        help="Continue downstream tasks after targeted task(s) complete",
    ),
    environment_id: str | None = typer.Option(
        None,
        "--environment-id",
        help="Run environment ID",
    ),
    environment_name: str | None = typer.Option(
        None,
        "--environment-name",
        help="Run environment name",
    ),
    run_input: list[str] = typer.Option(
        [],
        "--input",
        help="Pipeline input override as KEY=VAL. Repeat to set multiple values.",
    ),
    environment_override: list[str] = typer.Option(
        [],
        "--env",
        "-e",
        help="Environment variable override as KEY=VAL. Repeat to set multiple values.",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll the pipeline run until it completes",
    ),
    force: bool = typer.Option(
        False,
        "--force/--no-force",
        help="Ignore any warnings and run the pipeline anyway",
    ),
):
    """
    Run a pipeline in Orchestra.
    """
    api_key = require_api_key()
    if continue_downstream_run and not task:
        typer.echo(red("❌ --continue can only be used when --task/-t is provided"))
        raise typer.Exit(code=1)

    task_ids = _resolve_task_ids(task, path) if task else None
    environment = _resolve_environment_value(environment_id, environment_name)
    run_inputs = _parse_key_value_pairs(run_input, "--input") if run_input else None
    environment_overrides = (
        _build_environment_overrides(environment_override) if environment_override else None
    )
    selector = resolve_pipeline_selector(alias, pipeline_id, path, force=force)

    confirm_git_warnings_or_exit(force, path)
    run_selector = selector
    run_branch = branch
    run_commit = commit
    existing_pipeline: dict[str, object] | None = None
    if path is not None:
        existing_pipeline = _lookup_existing_pipeline(selector, api_key)

    if existing_pipeline is not None:
        provider = (storage_provider(existing_pipeline) or "ORCHESTRA").upper()
        if provider != "ORCHESTRA":
            run_selector = build_update_selector(existing_pipeline, "Run")
            if branch or commit:
                typer.echo(
                    red(
                        "❌ Run failed: --branch/-b and --commit/-c are not supported "
                        "for git-backed pipelines; run uses the selected YAML file's git state",
                    ),
                )
                raise typer.Exit(code=1)
            if path is None:
                typer.echo(red("❌ Run failed: --path is required for git-backed pipeline runs"))
                raise typer.Exit(code=1)
            run_branch, run_commit = prepare_git_backed_run_target(
                path=path,
                existing_pipeline=existing_pipeline,
                force=force,
                action=GitAction.RUN,
            )
            typer.echo(
                green(
                    f"✅ Using git-backed run target branch '{run_branch}' at commit {run_commit}",
                ),
            )

    start_pipeline_run(
        selector=run_selector,
        api_key=api_key,
        payload=build_run_payload(
            branch=run_branch,
            commit=run_commit,
            version_number=version_number,
            environment=environment,
            run_inputs=run_inputs,
            environment_overrides=environment_overrides,
            task_ids=task_ids,
            continue_downstream_run=continue_downstream_run if task_ids else None,
        ),
        wait=wait,
        failure_action="Run",
        existing_pipeline=existing_pipeline,
    )
