import re
from pathlib import Path
from typing import Any

import typer

from .git import detect_repo_root, detect_repository_slug
from .styling import bold, red, yellow

PipelineSelector = dict[str, str]


def pipeline_alias_option() -> Any:
    return typer.Option(None, "--alias", "-a", help="Pipeline alias")


def pipeline_id_option() -> Any:
    return typer.Option(None, "--pipeline-id", "-i", help="Pipeline id")


def pipeline_path_option(help_text: str = "Path to pipeline YAML") -> Any:
    return typer.Option(
        None,
        "--path",
        "-p",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help=help_text,
    )


def generate_alias_from_path(path: Path) -> str:
    alias = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return alias or "pipeline"


def resolve_pipeline_selector(
    *,
    alias: str | None,
    pipeline_id: str | None = None,
    path: Path | None = None,
    allow_pipeline_id: bool = True,
    required: bool = True,
) -> PipelineSelector:
    if alias:
        return {"alias": alias}

    if pipeline_id:
        if not allow_pipeline_id:
            typer.echo(red("--pipeline-id is not supported for this command"))
            raise typer.Exit(code=1)
        return {"pipeline_id": pipeline_id}

    if path is not None:
        return _resolve_path_selector(path)

    if required:
        typer.echo(red("Provide one of --alias, --pipeline-id, or --path"))
        raise typer.Exit(code=1)

    return {}


def selector_display(selector: PipelineSelector) -> str:
    if alias := selector.get("alias"):
        return f"alias: {alias}"
    if pipeline_id := selector.get("pipeline_id"):
        return f"pipeline_id: {pipeline_id}"
    if repository := selector.get("repository"):
        return f"repository: {repository}, yaml_path: {selector['yaml_path']}"
    return "no selector"


def _resolve_path_selector(path: Path) -> PipelineSelector:
    repo_root = detect_repo_root(path.parent)
    if repo_root is not None:
        repository = detect_repository_slug(repo_root)
        if repository is None:
            typer.echo(red("Could not detect repository URL from git"))
            raise typer.Exit(code=1)
        try:
            yaml_path = str(path.resolve().relative_to(repo_root.resolve()))
        except Exception:
            typer.echo(red("YAML file must be inside the git repository"))
            raise typer.Exit(code=1)
        return {"repository": repository, "yaml_path": yaml_path}

    generated_alias = generate_alias_from_path(path)
    typer.echo(yellow("Not inside a git repository; generating a pipeline alias from --path."))
    typer.echo(bold(f"Generated alias: {generated_alias}"))
    typer.echo(bold(yellow("Press Enter to accept this alias or Ctrl+C to abort")))
    try:
        input()
    except KeyboardInterrupt:
        typer.echo(red("Aborted"))
        raise typer.Exit(code=1)

    return {"alias": generated_alias}
