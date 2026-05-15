import difflib
from pathlib import Path
from typing import Any

import httpx
import typer

from ..utils.api import auth_headers, fail_with_response, request_or_exit, require_api_key
from ..utils.constants import get_api_url
from ..utils.git import (
    GitAction,
    build_compare_link,
    detect_current_branch,
    detect_default_branch,
    detect_repository_slug,
    detect_storage_provider,
    ensure_repo_relative_path,
    get_remote_url,
    is_branch_protection_error,
    push_branch,
    require_repo_root,
    run_git_command,
    stage_and_commit_file_if_needed,
    suggest_migration_branch_name,
)
from ..utils.pipeline_selector import PipelineSelector, pipeline_alias_option, pipeline_id_option
from ..utils.pipeline_update import storage_provider
from ..utils.styling import bold, green, red, yellow
from .pipeline_upsert import require_pipeline_body_from_success_response


def migrate_path_option() -> Any:
    return typer.Option(
        ...,
        "--path",
        "-p",
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path where the migrated pipeline YAML should live in the repository",
    )


def _resolve_migrate_selector(alias: str | None, pipeline_id: str | None) -> PipelineSelector:
    if alias:
        return PipelineSelector(alias=alias)
    if pipeline_id:
        return PipelineSelector(pipeline_id=pipeline_id)

    typer.echo(red("Provide one of --alias or --pipeline-id"))
    raise typer.Exit(code=1)


def _lookup_pipeline(selector: PipelineSelector, api_key: str) -> dict[str, object]:
    response = request_or_exit(
        httpx.get,
        get_api_url("pipeline"),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )
    if response.status_code != 200:
        raise fail_with_response("Migrate", response)
    return require_pipeline_body_from_success_response(response, "Migrate")


def _extract_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _extract_version(existing_pipeline: dict[str, object], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        version = _extract_int(existing_pipeline.get(key))
        if version is not None:
            return version
    return None


def _choose_migration_version(existing_pipeline: dict[str, object], force: bool) -> int | None:
    published_version = _extract_version(
        existing_pipeline,
        ("publishedVersionNumber", "published_version_number", "published_version", "published"),
    )
    latest_version = _extract_version(
        existing_pipeline,
        ("latestVersionNumber", "latest_version_number", "latest_version", "latest"),
    )

    if published_version is None and latest_version is None:
        return None
    if published_version is None:
        return latest_version
    if latest_version is None:
        return published_version
    if latest_version <= published_version:
        return published_version

    if force:
        typer.echo(
            yellow(
                "Detected published and newer latest pipeline versions; "
                "--force selected latest version for migration.",
            ),
        )
        return latest_version

    typer.echo(
        yellow(
            "Pipeline has both a published and a newer latest version. "
            "Choose which version to migrate (the other will be discarded).",
        ),
    )
    typer.echo(f"  1) Published version ({published_version})")
    typer.echo(f"  2) Latest version ({latest_version})")
    typer.echo(bold(yellow("Select 1 or 2, then press Enter (default: 2)")))
    try:
        choice = input().strip().lower()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)

    if choice in ("", "2", "latest", "l"):
        return latest_version
    if choice in ("1", "published", "p"):
        return published_version

    typer.echo(red("Invalid selection. Enter 1 for published or 2 for latest."))
    raise typer.Exit(code=1)


def _download_pipeline_yaml(selector: PipelineSelector, version: int | None, api_key: str) -> str:
    params = selector.to_payload()
    if version is not None:
        params["version"] = str(version)

    response = request_or_exit(
        httpx.get,
        get_api_url("pipeline/data"),
        params=params,
        timeout=30,
        headers=auth_headers(api_key),
    )
    if response.status_code != 200:
        raise fail_with_response("Migrate", response)

    try:
        body = response.json()
    except Exception:
        return response.text

    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        for key in ("yaml", "data", "content"):
            value = body.get(key)
            if isinstance(value, str):
                return value

    return response.text


def _yaml_contents_match(local_yaml: str, remote_yaml: str) -> bool:
    return local_yaml.strip() == remote_yaml.strip()


def _format_yaml_diff(path: Path, local_yaml: str, remote_yaml: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            local_yaml.splitlines(),
            remote_yaml.splitlines(),
            fromfile=f"{path} (local)",
            tofile="Orchestra (remote)",
            lineterm="",
        ),
    )
    return "\n".join(diff_lines)


def _prompt_conflict_resolution(force: bool) -> str:
    if force:
        typer.echo(
            yellow(
                "Local file differs from Orchestra YAML and --force is set; "
                "keeping the local file.",
            ),
        )
        return "local"

    typer.echo("  1) Overwrite local file with the Orchestra YAML")
    typer.echo("  2) Keep and use the local file")
    typer.echo("  3) Provide a different filepath")
    typer.echo(bold(yellow("Select 1, 2, or 3, then press Enter")))
    try:
        choice = input().strip().lower()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)

    if choice in ("1", "overwrite", "o"):
        return "overwrite"
    if choice in ("2", "local", "l"):
        return "local"
    if choice in ("3", "path", "p"):
        return "path"

    typer.echo(red("Invalid selection. Enter 1, 2, or 3."))
    raise typer.Exit(code=1)


def _prompt_new_path() -> Path:
    typer.echo(bold(yellow("Enter a new filepath for the YAML (relative paths are allowed):")))
    try:
        entered = input().strip()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)

    if not entered:
        typer.echo(red("Path cannot be empty"))
        raise typer.Exit(code=1)

    candidate = Path(entered).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _resolve_target_path_and_yaml(path: Path, remote_yaml: str, force: bool) -> tuple[Path, str]:
    selected_path = path
    selected_yaml = remote_yaml

    while selected_path.exists():
        local_yaml = selected_path.read_text()
        if _yaml_contents_match(local_yaml, remote_yaml):
            typer.echo(yellow(f"Local file already matches Orchestra YAML: {selected_path}"))
            return selected_path, local_yaml

        typer.echo(yellow(f"Local file differs from Orchestra YAML: {selected_path}"))
        diff_output = _format_yaml_diff(selected_path, local_yaml, remote_yaml)
        if diff_output:
            typer.echo(diff_output)

        resolution = _prompt_conflict_resolution(force)
        if resolution == "overwrite":
            return selected_path, remote_yaml
        if resolution == "local":
            return selected_path, local_yaml

        selected_path = _prompt_new_path()
        selected_yaml = remote_yaml

    return selected_path, selected_yaml


def _write_yaml(path: Path, yaml_content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_content)


def _prompt_branch_recovery(suggested_branch: str, force: bool) -> bool:
    if force:
        typer.echo(yellow(f"--force set; retrying push on suggested branch: {suggested_branch}"))
        return True

    typer.echo(yellow(f"Suggested branch for retry: {suggested_branch}"))
    typer.echo(bold(yellow("Create and push this branch now? [Y/n]")))
    try:
        response = input().strip().lower()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)
    return response in ("", "y", "yes")


def _push_migration_branch(repo_root: Path, branch_name: str, force: bool) -> str:
    ok, push_output = push_branch(repo_root, branch_name)
    if ok:
        return branch_name

    if not is_branch_protection_error(push_output):
        typer.echo(red("❌ Migrate failed: could not push changes to git"))
        if push_output:
            typer.echo(yellow(push_output))
        raise typer.Exit(code=1)

    typer.echo(red("❌ Push was blocked by branch protection on the current branch."))
    if push_output:
        typer.echo(yellow(push_output))

    suggested_branch = suggest_migration_branch_name()
    if not _prompt_branch_recovery(suggested_branch, force):
        typer.echo(red("Aborted migration because the YAML was not pushed to git"))
        raise typer.Exit(code=1)

    ok, checkout_output = run_git_command(["checkout", "-b", suggested_branch], repo_root)
    if not ok:
        typer.echo(red(f"❌ Migrate failed: could not create branch '{suggested_branch}'"))
        if checkout_output:
            typer.echo(yellow(checkout_output))
        raise typer.Exit(code=1)

    ok, retry_push_output = push_branch(repo_root, suggested_branch)
    if not ok:
        typer.echo(red(f"❌ Migrate failed: could not push branch '{suggested_branch}'"))
        if retry_push_output:
            typer.echo(yellow(retry_push_output))
        raise typer.Exit(code=1)

    return suggested_branch


def migrate_pipeline(
    path: Path = migrate_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
    working_branch: str | None = typer.Option(
        None,
        "--working-branch",
        help="Working branch to store in Orchestra (defaults to current branch)",
    ),
    default_branch: str | None = typer.Option(
        None,
        "--default-branch",
        help="Default branch to store in Orchestra (defaults to git remote default branch)",
    ),
    force: bool = typer.Option(
        False,
        "--force/--no-force",
        help="Skip interactive prompts and continue with inferred migration choices",
    ),
) -> None:
    """
    Migrate an Orchestra-backed pipeline to git-backed storage.
    """
    api_key = require_api_key()
    selector = _resolve_migrate_selector(alias, pipeline_id)

    repo_root = require_repo_root(path, GitAction.MIGRATE)

    repository_slug = detect_repository_slug(repo_root)
    if not repository_slug:
        typer.echo(red("Could not detect repository URL from git"))
        raise typer.Exit(code=1)

    storage_provider_value = detect_storage_provider(get_remote_url(repo_root))
    if not storage_provider_value:
        typer.echo(red("Could not detect storage provider - no matching host"))
        raise typer.Exit(code=1)

    if not default_branch:
        default_branch = detect_default_branch(repo_root)
        if not default_branch:
            typer.echo(red("Could not detect default branch from git"))
            raise typer.Exit(code=1)

    current_branch = detect_current_branch(repo_root, allow_detached=False)
    if not current_branch:
        typer.echo(red("Could not detect current branch from git"))
        raise typer.Exit(code=1)

    existing_pipeline = _lookup_pipeline(selector, api_key)
    provider = (storage_provider(existing_pipeline) or "ORCHESTRA").upper()
    if provider != "ORCHESTRA":
        typer.echo(
            red("Pipeline is already git-backed; only Orchestra-backed pipelines can be migrated"),
        )
        raise typer.Exit(code=1)

    target_version = _choose_migration_version(existing_pipeline, force)
    downloaded_yaml = _download_pipeline_yaml(selector, target_version, api_key)
    target_path, selected_yaml = _resolve_target_path_and_yaml(path, downloaded_yaml, force)
    _write_yaml(target_path, selected_yaml)

    relative_path = ensure_repo_relative_path(target_path, repo_root, GitAction.MIGRATE)
    pipeline_name = selector.alias or selector.pipeline_id or Path(relative_path).stem
    stage_and_commit_file_if_needed(
        repo_root,
        relative_path,
        f"Migrate pipeline '{pipeline_name}' to git-backed storage",
        GitAction.MIGRATE,
    )
    pushed_branch = _push_migration_branch(repo_root, current_branch, force)

    effective_working_branch = working_branch or pushed_branch
    payload: dict[str, str] = {
        "path": relative_path,
        "repository": repository_slug,
        "storage_provider": storage_provider_value,
        "default_branch": default_branch,
    }
    if effective_working_branch != default_branch:
        payload["working_branch"] = effective_working_branch

    response = request_or_exit(
        httpx.patch,
        get_api_url("pipelines/storage-settings"),
        params=selector.to_payload(),
        json=payload,
        timeout=30,
        headers=auth_headers(api_key),
    )
    if not (200 <= response.status_code < 300):
        raise fail_with_response("Migrate", response)

    typer.echo(
        green(
            "✅ Migrated pipeline "
            f"({selector.display()}) to git-backed storage at '{relative_path}'",
        ),
    )

    if pushed_branch != default_branch:
        compare_link = build_compare_link(
            storage_provider_value,
            repository_slug,
            default_branch,
            pushed_branch,
        )
        if compare_link:
            typer.echo(yellow(f"Open PR / compare link: {compare_link}"))
        else:
            typer.echo(
                yellow(
                    f"Pushed to branch '{pushed_branch}'. Open a PR against '{default_branch}'.",
                ),
            )

    raise typer.Exit(code=0)
