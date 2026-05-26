"""YAML loading + schema validation against the Orchestra API.

Shared by every command that takes a ``--path`` to a YAML file. Keeping it in
``utils/`` (rather than as private helpers on a command module) avoids one
command having to import private functions from another.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml

from .constants import get_api_url
from .styling import indent_message, red, yellow


class DuplicateKeyYAMLError(Exception):
    def __init__(self, loc: list[str], key: Any):
        self.loc = loc
        self.key = key
        super().__init__(f"Duplicate key found: {key!r}")


class DuplicateKeySafeLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self.path_stack: list[str] = []

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        # PyYAML passes this argument for recursive construction; this loader
        # always constructs keys/values deeply to track duplicate paths reliably.
        _ = deep
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}

        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            key_str = str(key)

            if key in mapping:
                raise DuplicateKeyYAMLError(loc=[*self.path_stack, key_str], key=key)

            self.path_stack.append(key_str)
            try:
                mapping[key] = self.construct_object(value_node, deep=True)
            finally:
                self.path_stack.pop()

        return mapping


def load_yaml(file: Path) -> tuple[dict | None, str | None]:
    """Read a YAML file and return ``(data, None)`` or ``(None, error_message)``."""
    try:
        with file.open("r") as f:
            data = yaml.load(f, Loader=DuplicateKeySafeLoader)
        return data, None
    except DuplicateKeyYAMLError as e:
        return (
            None,
            json.dumps(
                {
                    "detail": [
                        {
                            "loc": e.loc,
                            "msg": f"Duplicate key found in YAML: {e.key!r}",
                            "type": "value_error",
                        },
                    ],
                },
                indent=2,
            ),
        )
    except Exception as e:
        return None, str(e)


def validate_yaml_with_api(data: dict) -> tuple[bool, str | None]:
    """POST a YAML payload to the schema endpoint and return ``(ok, err_message)``."""
    try:
        response = httpx.post(get_api_url("pipelines/schema"), json=data, timeout=15)
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
