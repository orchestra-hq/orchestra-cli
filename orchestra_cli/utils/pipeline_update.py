import typer

from .pipeline_selector import PipelineSelector
from .styling import red


def build_update_selector(existing_pipeline: dict[str, object], action: str) -> PipelineSelector:
    for key in ("id", "pipeline_id"):
        pipeline_id = existing_pipeline.get(key)
        if isinstance(pipeline_id, str) and pipeline_id.strip():
            return PipelineSelector(pipeline_id=pipeline_id.strip())

    alias = existing_pipeline.get("alias")
    if alias:
        return PipelineSelector(alias=str(alias))

    typer.echo(
        red(f"❌ {action} failed: existing pipeline metadata did not include alias or pipeline id"),
    )
    raise typer.Exit(code=1)


def storage_provider(existing_pipeline: dict[str, object]) -> str | None:
    for key in ("storage_provider", "storageProvider"):
        value = existing_pipeline.get(key)
        if isinstance(value, str):
            return value
    return None
