import json
from pathlib import Path
from typing import cast

import httpx
import typer

from ..utils.api import auth_headers, fail_with_response, request_or_exit, require_api_key
from ..utils.constants import get_create_pipeline_url, get_pipeline_url, get_update_pipeline_url
from ..utils.git import confirm_git_warnings_or_exit
from ..utils.pipeline_selector import (
    PipelineSelector,
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.styling import green, indent_message, red, yellow
from ..utils.yaml_loader import load_validated_pipeline_data
from .pipeline_upsert import build_upsert_payload
from .run_pipeline import build_run_payload, start_pipeline_run


def _parse_success_response_body(response: httpx.Response, action: str) -> dict[str, object]:
    try:
        body = response.json()
    except Exception:
        typer.echo(red(f"❌ {action} failed: success response was not valid JSON"))
        typer.echo(yellow(indent_message(response.text)))
        raise typer.Exit(code=1)

    if not isinstance(body, dict):
        typer.echo(red(f"❌ {action} failed: success response was not a JSON object"))
        typer.echo(yellow(indent_message(json.dumps(body, indent=2))))
        raise typer.Exit(code=1)

    return cast(dict[str, object], body)


def _extract_pipeline_id(body: dict[str, object], action: str) -> str:
    pipeline_id = body.get("id")
    if pipeline_id is None:
        pipeline_id = body.get("pipeline_id")
    if not pipeline_id:
        typer.echo(red(f"❌ {action} failed: success response did not include pipeline id"))
        typer.echo(yellow(indent_message(json.dumps(body, indent=2))))
        raise typer.Exit(code=1)

    return str(pipeline_id)


def _extract_pipeline_version(body: dict[str, object], action: str) -> int:
    version_number = body.get("latestVersionNumber")
    if version_number is None:
        version_number = body.get("currentVersionNumber")
    if not isinstance(version_number, int):
        typer.echo(
            red(f"❌ {action} failed: success response did not include draft version number"),
        )
        raise typer.Exit(code=1)

    return version_number


def _extract_upsert_result(response: httpx.Response, action: str) -> tuple[str, int]:
    body = _parse_success_response_body(response, action)
    return _extract_pipeline_id(body, action), _extract_pipeline_version(body, action)


def _lookup_existing_pipeline(
    selector: PipelineSelector,
    api_key: str,
) -> dict[str, object] | None:
    response = request_or_exit(
        httpx.get,
        get_pipeline_url(),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        fail_with_response("Build", response)

    return _parse_success_response_body(response, "Build")


def _build_update_selector(existing_pipeline: dict[str, object]) -> PipelineSelector:
    pipeline_id = existing_pipeline.get("id") or existing_pipeline.get("pipeline_id")
    if pipeline_id:
        return PipelineSelector(pipeline_id=str(pipeline_id))

    alias = existing_pipeline.get("alias")
    if alias:
        return PipelineSelector(alias=str(alias))

    typer.echo(
        red("❌ Build failed: existing pipeline metadata did not include alias or pipeline id"),
    )
    raise typer.Exit(code=1)


def _build_create_selector(
    *,
    path: Path,
    alias: str | None,
    lookup_selector: PipelineSelector,
) -> PipelineSelector:
    if lookup_selector.alias:
        return PipelineSelector(alias=lookup_selector.alias)

    return resolve_pipeline_selector(
        alias,
        path=path,
        allow_pipeline_id=False,
        use_git_path_selector=False,
    )


def _storage_provider(existing_pipeline: dict[str, object]) -> str | None:
    for key in ("storage_provider", "storageProvider"):
        value = existing_pipeline.get(key)
        if isinstance(value, str):
            return value
    return None


def _upsert_draft_pipeline(
    *,
    alias: str | None,
    path: Path,
    lookup_selector: PipelineSelector,
    api_key: str,
) -> tuple[PipelineSelector, int]:
    data = load_validated_pipeline_data(path)
    existing_pipeline = _lookup_existing_pipeline(lookup_selector, api_key)

    if existing_pipeline is None:
        create_selector = _build_create_selector(
            path=path,
            alias=alias,
            lookup_selector=lookup_selector,
        )
        payload = build_upsert_payload(data, publish=False, selector=create_selector)

        typer.echo(f"Creating draft pipeline ({create_selector.display()})")
        create_response = request_or_exit(
            httpx.post,
            get_create_pipeline_url(),
            json=payload,
            timeout=30,
            headers=auth_headers(api_key),
        )

        if create_response.status_code == 201:
            pipeline_id, version_number = _extract_upsert_result(create_response, "Build")
            typer.echo(
                green(
                    "✅ Draft pipeline "
                    f"({create_selector.display()}) created as version {version_number}",
                ),
            )
            return PipelineSelector(pipeline_id=pipeline_id), version_number

        fail_with_response("Build", create_response)
        raise typer.Exit(code=1)

    assert existing_pipeline is not None
    storage_provider = _storage_provider(existing_pipeline)
    if storage_provider is not None and storage_provider != "ORCHESTRA":
        typer.echo(
            red(
                "❌ Build failed: git-backed pipelines are not yet supported by this command",
            ),
        )
        raise typer.Exit(code=1)

    update_selector = _build_update_selector(existing_pipeline)
    payload = build_upsert_payload(data, publish=False, selector=update_selector)

    typer.echo(f"Updating draft pipeline ({update_selector.display()})")
    update_response = request_or_exit(
        httpx.put,
        get_update_pipeline_url(),
        json=payload,
        timeout=30,
        headers=auth_headers(api_key),
    )

    if update_response.status_code == 200:
        pipeline_id, version_number = _extract_upsert_result(update_response, "Build")
        typer.echo(
            green(
                "✅ Draft pipeline "
                f"({update_selector.display()}) updated as version {version_number}",
            ),
        )
        return PipelineSelector(pipeline_id=pipeline_id), version_number

    fail_with_response("Build", update_response)
    raise typer.Exit(code=1)


def build_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Git branch name"),
    commit: str | None = typer.Option(None, "--commit", "-c", help="Commit SHA"),
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
) -> None:
    """
    Validate local YAML, create or update a draft pipeline, and start the draft version.
    """
    api_key = require_api_key()
    if path is None:
        typer.echo(red("Provide --path to build a pipeline from YAML"))
        raise typer.Exit(code=1)
    lookup_selector = resolve_pipeline_selector(alias, pipeline_id, path)

    confirm_git_warnings_or_exit(force, path)
    run_selector, version_number = _upsert_draft_pipeline(
        alias=alias,
        path=path,
        lookup_selector=lookup_selector,
        api_key=api_key,
    )

    start_pipeline_run(
        selector=run_selector,
        api_key=api_key,
        payload=build_run_payload(
            run_selector,
            branch=branch,
            commit=commit,
            version_number=version_number,
        ),
        wait=wait,
        failure_action="Build",
    )
