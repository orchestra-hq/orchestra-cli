import re
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel

from .git import detect_repo_root, detect_repository_slug
from .styling import bold, red, yellow


class PipelineSelector(BaseModel):
    alias: str | None = None
    pipeline_id: str | None = None
    repository: str | None = None
    yaml_path: str | None = None

    def to_payload(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.model_dump(exclude_none=True).items()}

    def display(self) -> str:
        if self.alias:
            return f"alias: {self.alias}"
        if self.pipeline_id:
            return f"pipeline_id: {self.pipeline_id}"
        if self.repository and self.yaml_path:
            return f"repository: {self.repository}, yaml_path: {self.yaml_path}"
        return "no selector"


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
    alias: str | None,
    pipeline_id: str | None = None,
    path: Path | None = None,
    allow_pipeline_id: bool = True,
    required: bool = True,
    use_git_path_selector: bool = True,
    force: bool = False,
) -> PipelineSelector:
    if alias:
        return PipelineSelector(alias=alias)

    if pipeline_id:
        if not allow_pipeline_id:
            typer.echo(red("Passing pipeline IDs is not supported for this command"))
            raise typer.Exit(code=1)
        return PipelineSelector(pipeline_id=pipeline_id)

    if path is not None and use_git_path_selector:
        return _resolve_path_selector(path, force=force)

    if path is not None:
        return _resolve_generated_alias_selector(
            path,
            inside_git_repo=detect_repo_root(path.parent) is not None,
            force=force,
        )

    if required:
        typer.echo(red("Provide one of --alias, --pipeline-id, or --path"))
        raise typer.Exit(code=1)

    return PipelineSelector()


def _resolve_path_selector(path: Path, force: bool = False) -> PipelineSelector:
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
        return PipelineSelector(repository=repository, yaml_path=yaml_path)

    return _resolve_generated_alias_selector(path, inside_git_repo=False, force=force)


def _resolve_generated_alias_selector(
    path: Path,
    inside_git_repo: bool,
    force: bool = False,
) -> PipelineSelector:
    generated_alias = generate_alias_from_path(path)
    if inside_git_repo:
        typer.echo(yellow("This command uses an alias selector; generating one from --path."))
    else:
        typer.echo(yellow("Not inside a git repository; generating a pipeline alias from --path."))
    typer.echo(bold(f"Generated alias: {generated_alias}"))
    if not force:
        typer.echo(bold(yellow("Press Enter to accept this alias or Ctrl+C to abort")))
        try:
            input()
        except KeyboardInterrupt:
            typer.echo(red("Aborted"))
            raise typer.Exit(code=1)

    return PipelineSelector(alias=generated_alias)
