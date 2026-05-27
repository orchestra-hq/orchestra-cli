import json
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml

from ..utils.api import request_or_exit
from ..utils.constants import get_api_url
from ..utils.styling import bold, green, indent_message, red, yellow
from ..utils.yaml_loader import load_yaml


def get_yaml_snippet(data: Any, loc: list[Any]) -> dict[str, Any] | None:
    weird_keys = ["TaskGroupModel"]
    try:
        for idx, key in enumerate(loc):
            if key not in weird_keys:
                if key not in data:
                    return {loc[idx - 1]: data}
                data = data[key]
        return {loc[-1]: data}
    except Exception:
        return None


def _render_validation_details(details: list[dict[str, Any]], data: Any) -> None:
    for detail in details:
        loc = detail.get("loc", [])
        msg = detail.get("msg", "Unknown error")
        typer.echo(bold(yellow(f"Error at: {'.'.join(str(x) for x in loc)}")))
        typer.echo(red(indent_message(msg)))
        snippet = get_yaml_snippet(data or {}, loc)
        if snippet is not None:
            typer.echo(bold("\nYAML snippet:"))
            typer.echo(yaml.dump(snippet, sort_keys=False, default_flow_style=False))
        else:
            typer.echo(yellow("(Could not locate this path in your YAML)"))


def validate(file: Path = typer.Argument(..., help="YAML file to validate")):
    """
    Validate a YAML file against the API.
    """
    if not file.exists():
        typer.echo(red(f"File not found: {file}"))
        raise typer.Exit(code=1)

    data, err = load_yaml(file)
    if err is not None:
        try:
            local_errors = json.loads(err)
        except (json.JSONDecodeError, TypeError):
            pass
        else:
            details = local_errors.get("detail")
            if isinstance(details, list):
                typer.echo(red("❌ Validation failed with status 422\n"))
                _render_validation_details(details, data)
                raise typer.Exit(code=1)

        typer.echo(red(f"Invalid YAML: {err}"))
        raise typer.Exit(code=1)

    response = request_or_exit(httpx.post, get_api_url("pipelines/schema"), json=data, timeout=10)

    if response.status_code == 200:
        typer.echo(green("✅ Validation passed!"))
        raise typer.Exit(code=0)

    typer.echo(red(f"❌ Validation failed with status {response.status_code}\n"))
    try:
        errors = response.json()
        details = errors.get("detail")
        if details and isinstance(details, list):
            _render_validation_details(details, data)
        else:
            typer.echo(errors)
    except Exception:
        typer.echo(response.text)
    raise typer.Exit(code=1)
