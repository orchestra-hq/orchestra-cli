import json
import re
from pathlib import Path
from typing import cast

import httpx
import typer

from ..utils.api import (
    auth_headers,
    fail_with_response,
    request_or_exit,
    require_api_key,
)
from ..utils.constants import get_pipeline_url
from ..utils.pipeline_selector import (
    pipeline_alias_option,
    pipeline_id_option,
    pipeline_path_option,
    resolve_pipeline_selector,
)
from ..utils.styling import indent_message, red, yellow

_PREFERRED_FIELD_ORDER = (
    "id",
    "pipeline_id",
    "alias",
    "name",
    "description",
    "repository",
    "yaml_path",
    "storage_provider",
    "published",
    "latestRunStatus",
    "latest_run_status",
    "latestRunId",
    "latest_run_id",
    "createdAt",
    "created_at",
    "updatedAt",
    "updated_at",
)


def get_pipeline(
    path: Path | None = pipeline_path_option(),
    alias: str | None = pipeline_alias_option(),
    pipeline_id: str | None = pipeline_id_option(),
):
    """
    Fetch one pipeline using the shared selector model.
    """
    api_key = require_api_key()
    selector = resolve_pipeline_selector(alias, pipeline_id, path)

    response = request_or_exit(
        httpx.get,
        get_pipeline_url(),
        params=selector.to_payload(),
        timeout=30,
        headers=auth_headers(api_key),
    )

    if response.status_code == 200:
        try:
            body = response.json()
        except Exception:
            typer.echo(red("❌ Get pipeline failed: success response was not valid JSON"))
            typer.echo(yellow(indent_message(response.text)))
            raise typer.Exit(code=1)

        if not isinstance(body, dict):
            typer.echo(red("❌ Get pipeline failed: success response was not a JSON object"))
            typer.echo(yellow(indent_message(json.dumps(body, indent=2))))
            raise typer.Exit(code=1)

        pipeline = cast(dict[str, object], body)
        typer.echo(_format_pipeline_metadata(pipeline))
        raise typer.Exit(code=0)

    raise fail_with_response("Get pipeline", response)


def _format_pipeline_metadata(pipeline: dict[str, object]) -> str:
    lines: list[str] = []
    emitted = set()

    for key in _ordered_keys(pipeline):
        value = pipeline[key]
        if value is None:
            continue

        label = _humanize_key(key)
        formatted_value = _format_value(value)
        if "\n" in formatted_value:
            lines.append(f"  {label}:")
            lines.append(indent_message(formatted_value))
        else:
            lines.append(f"  {label}: {formatted_value}")
        emitted.add(key)

    if not emitted:
        lines.append("  No metadata returned")

    return "\n".join(["Pipeline", *lines])


def _ordered_keys(pipeline: dict[str, object]) -> list[str]:
    preferred_keys = [key for key in _PREFERRED_FIELD_ORDER if key in pipeline]
    remaining_keys = sorted(key for key in pipeline if key not in _PREFERRED_FIELD_ORDER)
    return [*preferred_keys, *remaining_keys]


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return str(value)


def _humanize_key(key: str) -> str:
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", key).replace("_", " ").replace("-", " ")
    replacements = {
        "api": "API",
        "id": "ID",
        "url": "URL",
        "yaml": "YAML",
    }
    return " ".join(replacements.get(word.lower(), word.title()) for word in words.split())
