from pathlib import Path

import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_delete_pipeline_url
from ..utils.pipeline_selector import (
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.styling import green, yellow


def delete_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
):
    """
    Delete a pipeline by selector.
    """
    api_key = require_api_key()
    selector = resolve_pipeline_selector(alias, pipeline_id, path)

    if not typer.confirm(f"Delete pipeline ({selector.display()})?"):
        typer.echo(yellow("Deletion aborted"))
        raise typer.Exit(code=1)

    response = request_or_exit(
        httpx.delete,
        get_delete_pipeline_url(),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 204:
        typer.echo(green(f"✅ Pipeline ({selector.display()}) deleted successfully"))
        raise typer.Exit(code=0)

    raise fail_with_response("Delete", response)
