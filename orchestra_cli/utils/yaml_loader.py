"""YAML loading + schema validation against the Orchestra API.

Shared by every command that takes a ``--path`` to a YAML file. Keeping it in
``utils/`` (rather than as private helpers on a command module) avoids one
command having to import private functions from another.
"""

import json
from pathlib import Path

import httpx
import typer
import yaml

from .constants import get_api_url
from .styling import indent_message, red, yellow


def load_yaml(file: Path) -> tuple[dict | None, str | None]:
    """Read a YAML file and return ``(data, None)`` or ``(None, error_message)``."""
    try:
        with file.open("r") as f:
            data = yaml.safe_load(f)
        return data, None
    except Exception as e:
        return None, str(e)


def validate_yaml_with_api(data: dict) -> tuple[bool, str | None]:
    """POST a YAML payload to the schema endpoint and return ``(ok, err_message)``."""
    try:
        response = httpx.post(get_api_url("schema"), json=data, timeout=15)
    except Exception as e:
        return False, f"HTTP request failed: {e}"

    if response.status_code == 200:
        return True, None
    try:
        errors = response.json()
        return False, json.dumps(errors, indent=2)
    except Exception:
        return False, response.text


def load_validated_pipeline_data(path: Path) -> dict:
    """Load YAML and run it through the schema endpoint, exiting cleanly on failure."""
    if not path.exists():
        typer.echo(red(f"File not found: {path}"))
        raise typer.Exit(code=1)

    data, err = load_yaml(path)
    if err is not None:
        typer.echo(red(f"Invalid YAML: {err}"))
        raise typer.Exit(code=1)

    ok, err_msg = validate_yaml_with_api(data or {})
    if not ok:
        typer.echo(red("❌ Validation failed"))
        if err_msg:
            typer.echo(yellow(indent_message(err_msg)))
        raise typer.Exit(code=1)

    return data or {}
