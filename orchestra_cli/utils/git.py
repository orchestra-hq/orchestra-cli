from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git_command(args: list[str], cwd: Path) -> tuple[bool, str]:
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
    ok, out = _run_git_command(["rev-parse", "--show-toplevel"], start_path)
    if not ok:
        return None
    return Path(out)


def git_warnings(repo_root: Path) -> list[str]:
    warnings: list[str] = []
    # Uncommitted changes
    ok, out = _run_git_command(["status", "--porcelain"], repo_root)
    if ok and out:
        warnings.append("Uncommitted changes detected in repository")

    # Not on latest commit of the branch / local vs remote mismatch
    # Try to compare local HEAD to upstream if it exists
    ok, branch = _run_git_command(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        repo_root,
    )
    if ok and branch:
        ok_head, head = _run_git_command(["rev-parse", "HEAD"], repo_root)
        ok_up, upstream = _run_git_command(["rev-parse", "@{u}"], repo_root)
        if ok_head and ok_up and head and upstream and head != upstream:
            warnings.append("Local branch SHA does not match remote branch SHA")
            # If behind, call out explicitly
            ok_stat, stat = _run_git_command(["status", "-sb"], repo_root)
            if ok_stat and "behind" in stat:
                warnings.append("You are not on latest HEAD of the branch (behind remote)")
    return warnings
