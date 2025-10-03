from pathlib import Path
from typing import Any

import httpx
import typer
import yaml

from ..utils.constants import API_URL
from ..utils.styling import bold, green, indent_message, red, yellow


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


def validate(file: Path = typer.Argument(..., help="YAML file to validate")):
    """
    Validate a YAML file against the API.
    """
    if not file.exists():
        typer.echo(red(f"File not found: {file}"))
        raise typer.Exit(code=1)

    try:
        with file.open("r") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        typer.echo(red(f"Invalid YAML: {e}"))
        raise typer.Exit(code=1)

    try:
        response = httpx.post(API_URL.format("schema"), json=data, timeout=10)
    except Exception as e:
        typer.echo(red(f"HTTP request failed: {e}"))
        raise typer.Exit(code=1)

    if response.status_code == 200:
        typer.echo(green("✅ Validation passed!"))
        raise typer.Exit(code=0)
    else:
        typer.echo(red(f"❌ Validation failed with status {response.status_code}\n"))
        try:
            errors = response.json()
            details = errors.get("detail")
            if details and isinstance(details, list):
                for err in details:
                    loc = err.get("loc", [])
                    msg = err.get("msg", "Unknown error")
                    typer.echo(bold(yellow(f"Error at: {'.'.join(str(x) for x in loc)}")))
                    typer.echo(red(indent_message(msg)))
                    snippet = get_yaml_snippet(data, loc)
                    if snippet is not None:
                        typer.echo(bold("\nYAML snippet:"))
                        typer.echo(yaml.dump(snippet, sort_keys=False, default_flow_style=False))
                    else:
                        typer.echo(yellow("(Could not locate this path in your YAML)"))
            else:
                typer.echo(errors)
        except Exception:
            typer.echo(response.text)
        raise typer.Exit(code=1)
