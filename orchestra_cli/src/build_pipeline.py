import random
import string
from pathlib import Path

import httpx
import typer

from ..utils.api import auth_headers, fail_with_response, request_or_exit, require_api_key
from ..utils.constants import get_create_pipeline_url, get_pipeline_url, get_update_pipeline_url
from ..utils.git import confirm_git_warnings_or_exit, detect_repo_root, run_git_command
from ..utils.pipeline_selector import (
    PipelineSelector,
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.styling import bold, green, red, yellow
from ..utils.yaml_loader import load_validated_pipeline_data
from .pipeline_upsert import (
    build_upsert_payload,
    require_pipeline_body_from_success_response,
    require_pipeline_id_from_success_body,
)
from .run_pipeline import build_run_payload, start_pipeline_run


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
    body = require_pipeline_body_from_success_response(response, action)
    return require_pipeline_id_from_success_body(body, action), _extract_pipeline_version(
        body,
        action,
    )


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
        raise fail_with_response("Build", response)

    return require_pipeline_body_from_success_response(response, "Build")


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
    path: Path,
    lookup_selector: PipelineSelector,
    force: bool,
) -> PipelineSelector:
    if lookup_selector.alias:
        return PipelineSelector(alias=lookup_selector.alias)

    return resolve_pipeline_selector(
        None,
        path=path,
        allow_pipeline_id=False,
        use_git_path_selector=False,
        force=force,
    )


def _storage_provider(existing_pipeline: dict[str, object]) -> str | None:
    for key in ("storage_provider", "storageProvider"):
        value = existing_pipeline.get(key)
        if isinstance(value, str):
            return value
    return None


def _suggest_migration_branch_name() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"orchestra-migrate-pipeline-{suffix}"


def _require_repo_root(path: Path) -> Path:
    repo_root = detect_repo_root(path.parent)
    if repo_root is not None:
        return repo_root

    typer.echo(red("❌ Build failed: YAML file must be inside a git repository"))
    raise typer.Exit(code=1)


def _require_repo_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        typer.echo(red("❌ Build failed: YAML file must be inside the git repository"))
        raise typer.Exit(code=1)


def _require_current_branch(repo_root: Path) -> str:
    ok, branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    if ok and branch:
        return branch

    typer.echo(red("❌ Build failed: could not determine current git branch"))
    if branch:
        typer.echo(yellow(branch))
    raise typer.Exit(code=1)


def _require_head_commit(repo_root: Path) -> str:
    ok, head_commit = run_git_command(["rev-parse", "HEAD"], repo_root)
    if ok and head_commit:
        return head_commit

    typer.echo(red("❌ Build failed: could not determine current git commit SHA"))
    if head_commit:
        typer.echo(yellow(head_commit))
    raise typer.Exit(code=1)


def _file_has_uncommitted_changes(repo_root: Path, relative_path: str) -> bool:
    ok, out = run_git_command(["status", "--porcelain", "--", relative_path], repo_root)
    return bool(ok and out)


def _head_is_unpushed(repo_root: Path) -> bool:
    has_upstream, _ = run_git_command(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        repo_root,
    )
    if not has_upstream:
        return True

    ok, counts = run_git_command(["rev-list", "--left-right", "--count", "@{u}...HEAD"], repo_root)
    if ok:
        parts = counts.split()
        if len(parts) == 2 and parts[1].isdigit():
            return int(parts[1]) > 0

    ok, status_output = run_git_command(["status", "-sb"], repo_root)
    if ok:
        return "ahead " in status_output or "ahead]" in status_output

    return False


def _prompt_or_abort(message: str) -> None:
    typer.echo(bold(yellow(message)))
    try:
        input()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)


def _input_with_default(prompt: str, default: str, force: bool) -> str:
    if force:
        return default

    typer.echo(bold(yellow(f"{prompt}")))
    typer.echo(bold(yellow(f"Press Enter to accept: {default}")))
    try:
        value = input().strip()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)
    return value or default


def _pipeline_name_for_commit_message(existing_pipeline: dict[str, object], path: Path) -> str:
    alias = existing_pipeline.get("alias")
    if isinstance(alias, str) and alias:
        return alias
    return path.stem


def _stage_selected_file(repo_root: Path, relative_path: str) -> None:
    ok, output = run_git_command(["add", "--", relative_path], repo_root)
    if ok:
        return

    typer.echo(red("❌ Build failed: could not stage selected YAML file"))
    if output:
        typer.echo(yellow(output))
    raise typer.Exit(code=1)


def _commit_selected_file(repo_root: Path, commit_message: str) -> tuple[bool, str]:
    return run_git_command(["commit", "-m", commit_message], repo_root)


def _push_current_branch(repo_root: Path) -> tuple[bool, str]:
    branch = _require_current_branch(repo_root)
    has_upstream, _ = run_git_command(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        repo_root,
    )
    if has_upstream:
        return run_git_command(["push"], repo_root)
    return run_git_command(["push", "-u", "origin", branch], repo_root)


def _push_branch(repo_root: Path, branch_name: str) -> tuple[bool, str]:
    return run_git_command(["push", "-u", "origin", branch_name], repo_root)


def _recover_on_new_branch(
    *,
    repo_root: Path,
    relative_path: str,
    commit_message: str | None,
    include_file_changes: bool,
    commit_was_created: bool,
    failure_output: str,
    force: bool,
) -> tuple[str, str]:
    typer.echo(red("❌ Build failed while committing/pushing on the current branch."))
    if failure_output:
        typer.echo(yellow(failure_output))

    if not force:
        _prompt_or_abort(
            "Press Enter to continue by creating a new branch, or Ctrl+C to abort",
        )

    should_recommit_on_new_branch = include_file_changes and not commit_was_created
    if commit_was_created:
        should_cleanup = False
        if not force:
            typer.echo(
                bold(
                    yellow(
                        "Type 'reset' then Enter to remove the local commit before retrying, "
                        "or press Enter to keep it",
                    ),
                ),
            )
            try:
                should_cleanup = input().strip().lower() == "reset"
            except KeyboardInterrupt:
                typer.echo(red("Aborted"))
                raise typer.Exit(code=1)

        if should_cleanup:
            ok, reset_output = run_git_command(["reset", "--soft", "HEAD~1"], repo_root)
            if not ok:
                typer.echo(red("❌ Build failed: could not clean up local commit"))
                if reset_output:
                    typer.echo(yellow(reset_output))
                raise typer.Exit(code=1)
            should_recommit_on_new_branch = include_file_changes

    suggested_branch = _suggest_migration_branch_name()
    target_branch = _input_with_default(
        "Confirm branch name for retry",
        suggested_branch,
        force,
    )

    ok, checkout_output = run_git_command(["checkout", "-b", target_branch], repo_root)
    if not ok:
        typer.echo(red(f"❌ Build failed: could not create branch '{target_branch}'"))
        if checkout_output:
            typer.echo(yellow(checkout_output))
        raise typer.Exit(code=1)

    if should_recommit_on_new_branch:
        if not commit_message:
            typer.echo(red("❌ Build failed: missing commit message for retry commit"))
            raise typer.Exit(code=1)
        _stage_selected_file(repo_root, relative_path)
        ok, commit_output = _commit_selected_file(repo_root, commit_message)
        if not ok:
            typer.echo(red("❌ Build failed: could not commit changes on the new branch"))
            if commit_output:
                typer.echo(yellow(commit_output))
            raise typer.Exit(code=1)

    ok, push_output = _push_branch(repo_root, target_branch)
    if not ok:
        typer.echo(red(f"❌ Build failed: couldn't push generated branch '{target_branch}'"))
        if push_output:
            typer.echo(yellow(push_output))
        raise typer.Exit(code=1)

    return target_branch, _require_head_commit(repo_root)


def _prepare_git_backed_run_target(
    *,
    path: Path,
    existing_pipeline: dict[str, object],
    force: bool,
) -> tuple[str, str]:
    repo_root = _require_repo_root(path)
    relative_path = _require_repo_relative_path(path, repo_root)
    include_file_changes = _file_has_uncommitted_changes(repo_root, relative_path)
    has_unpushed_head = _head_is_unpushed(repo_root)

    if not include_file_changes and not has_unpushed_head:
        return _require_current_branch(repo_root), _require_head_commit(repo_root)

    commit_message: str | None = None
    commit_was_created = False
    if include_file_changes:
        pipeline_name = _pipeline_name_for_commit_message(existing_pipeline, path)
        commit_message = _input_with_default(
            "Confirm commit message for selected YAML changes",
            f"Migrating pipeline: '{pipeline_name}'",
            force,
        )
        _stage_selected_file(repo_root, relative_path)
        ok, commit_output = _commit_selected_file(repo_root, commit_message)
        if not ok:
            return _recover_on_new_branch(
                repo_root=repo_root,
                relative_path=relative_path,
                commit_message=commit_message,
                include_file_changes=include_file_changes,
                commit_was_created=False,
                failure_output=commit_output,
                force=force,
            )
        commit_was_created = True

    ok, push_output = _push_current_branch(repo_root)
    if not ok:
        return _recover_on_new_branch(
            repo_root=repo_root,
            relative_path=relative_path,
            commit_message=commit_message,
            include_file_changes=include_file_changes,
            commit_was_created=commit_was_created,
            failure_output=push_output,
            force=force,
        )

    return _require_current_branch(repo_root), _require_head_commit(repo_root)


def _create_draft_pipeline(
    path: Path,
    lookup_selector: PipelineSelector,
    pipeline_data: dict[str, object],
    force: bool,
    api_key: str,
) -> tuple[PipelineSelector, int]:
    create_selector = _build_create_selector(path, lookup_selector, force)
    payload = build_upsert_payload(pipeline_data, publish=False, selector=create_selector)

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

    raise fail_with_response("Build", create_response)


def _update_draft_pipeline(
    existing_pipeline: dict[str, object],
    pipeline_data: dict[str, object],
    api_key: str,
) -> tuple[PipelineSelector, int]:
    update_selector = _build_update_selector(existing_pipeline)
    payload = build_upsert_payload(pipeline_data, publish=False, selector=update_selector)

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

    raise fail_with_response("Build", update_response)


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
        typer.echo(
            red("A pipeline YAML file path is required (use -p or --path with your YAML file)"),
        )
        raise typer.Exit(code=1)
    lookup_selector = resolve_pipeline_selector(alias, pipeline_id, path, force=force)

    confirm_git_warnings_or_exit(force, path)
    pipeline_data = load_validated_pipeline_data(path)
    existing_pipeline = _lookup_existing_pipeline(lookup_selector, api_key)

    if existing_pipeline is None:
        run_selector, version_number = _create_draft_pipeline(
            path=path,
            lookup_selector=lookup_selector,
            pipeline_data=pipeline_data,
            force=force,
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
        return

    storage_provider = _storage_provider(existing_pipeline)
    if storage_provider is None or storage_provider == "ORCHESTRA":
        run_selector, version_number = _update_draft_pipeline(
            existing_pipeline=existing_pipeline,
            pipeline_data=pipeline_data,
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
        return

    run_selector = _build_update_selector(existing_pipeline)
    git_branch, git_commit = _prepare_git_backed_run_target(
        path=path,
        existing_pipeline=existing_pipeline,
        force=force,
    )
    typer.echo(
        green(
            f"✅ Using git-backed build target branch '{git_branch}' at commit {git_commit}",
        ),
    )

    start_pipeline_run(
        selector=run_selector,
        api_key=api_key,
        payload=build_run_payload(
            run_selector,
            branch=git_branch,
            commit=git_commit,
        ),
        wait=wait,
        failure_action="Build",
    )
