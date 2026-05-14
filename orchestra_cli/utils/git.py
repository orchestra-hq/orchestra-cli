import random
import re
import string
import subprocess
from pathlib import Path

import typer

from .styling import bold, red, yellow


def run_git_command(args: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except Exception as e:
        return False, str(e)


def detect_repo_root(start_path: Path) -> Path | None:
    ok, out = run_git_command(["rev-parse", "--show-toplevel"], start_path)
    if not ok:
        return None
    return Path(out)


def detect_repository_slug(repo_root: Path) -> str | None:
    ok, remote = run_git_command(["remote", "get-url", "origin"], repo_root)
    if not ok or not remote:
        return None

    cleaned_remote = re.sub(r"/(?:_git|scm|v3)(?=/)", "", remote.strip())
    pattern = r".*[:/]([^/]+)/([^/]+?)(?:\.git)?/?$"

    if match := re.search(pattern, cleaned_remote):
        return f"{match.group(1)}/{match.group(2)}"

    return None


def git_warnings(repo_root: Path) -> list[str]:
    warnings: list[str] = []
    # Uncommitted changes
    ok, out = run_git_command(["status", "--porcelain"], repo_root)
    if ok and out:
        warnings.append("Uncommitted changes detected in repository")

    # Not on latest commit of the branch / local vs remote mismatch
    # Try to compare local HEAD to upstream if it exists
    ok, branch = run_git_command(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        repo_root,
    )
    if ok and branch:
        ok_head, head = run_git_command(["rev-parse", "HEAD"], repo_root)
        ok_up, upstream = run_git_command(["rev-parse", "@{u}"], repo_root)
        if ok_head and ok_up and head and upstream and head != upstream:
            warnings.append("Local branch SHA does not match remote branch SHA")
            # If behind, call out explicitly
            ok_stat, stat = run_git_command(["status", "-sb"], repo_root)
            if ok_stat and "behind" in stat:
                warnings.append("You are not on latest HEAD of the branch (behind remote)")
    return warnings


def confirm_git_warnings_or_exit(force: bool, path: Path | None = None) -> None:
    """Show git warnings and require confirmation unless ``--force`` is passed."""
    start_path = path.parent if path is not None else Path.cwd()
    repo_root = detect_repo_root(start_path)
    if repo_root is None:
        return

    warnings = git_warnings(repo_root)
    if not warnings:
        return

    for warning in warnings:
        typer.echo(yellow(f"⚠ {warning}"))

    if force:
        return

    typer.echo(bold(yellow("Press Enter to continue or Ctrl+C to abort")))
    try:
        input()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)


def suggest_migration_branch_name() -> str:
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

    typer.echo(bold(yellow(prompt)))
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
        _prompt_or_abort("Press Enter to continue by creating a new branch, or Ctrl+C to abort")

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

    suggested_branch = suggest_migration_branch_name()
    target_branch = _input_with_default("Confirm branch name for retry", suggested_branch, force)

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


def prepare_git_backed_run_target(
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
                repo_root,
                relative_path,
                commit_message,
                include_file_changes,
                False,
                commit_output,
                force,
            )
        commit_was_created = True

    ok, push_output = _push_current_branch(repo_root)
    if not ok:
        return _recover_on_new_branch(
            repo_root,
            relative_path,
            commit_message,
            include_file_changes,
            commit_was_created,
            push_output,
            force,
        )

    return _require_current_branch(repo_root), _require_head_commit(repo_root)
