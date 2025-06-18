import yaml
import httpx
import typer
from pathlib import Path
from typing import Any, List

app = typer.Typer(help="Orchestra CLI – perform operations with Orchestra locally.")

API_URL = "https://app.getorchestra.io/api/engine/public/pipelines/schema"


# Colors
def red(msg):
    return typer.style(msg, fg=typer.colors.RED, bold=True)


def green(msg):
    return typer.style(msg, fg=typer.colors.GREEN, bold=True)


def yellow(msg):
    return typer.style(msg, fg=typer.colors.YELLOW, bold=True)


def bold(msg):
    return typer.style(msg, bold=True)


def indent_message(msg: str, indent: str = "  ") -> str:
    return "\n".join(indent + line for line in msg.splitlines())


def get_yaml_snippet(data: Any, loc: List[Any]) -> dict[str, Any]:
    weird_keys = ["TaskGroupModel"]
    try:
        for key in loc:
            if key not in weird_keys:
                data = data[key]
        return {loc[-1]: data}
    except Exception:
        return None


@app.command()
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
        response = httpx.post(API_URL, json=data, timeout=10)
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
                    typer.echo(
                        bold(yellow(f"Error at: {'.'.join(str(x) for x in loc)}"))
                    )
                    typer.echo(red(indent_message(msg)))
                    snippet = get_yaml_snippet(data, loc)
                    if snippet is not None:
                        typer.echo(bold("\nYAML snippet:"))
                        typer.echo(
                            yaml.dump(
                                snippet, sort_keys=False, default_flow_style=False
                            )
                        )
                    else:
                        typer.echo(
                            yellow("(Could not locate this path in your YAML)")
                        )
                    typer.echo("")
            else:
                typer.echo(errors)
        except Exception:
            typer.echo(response.text)
        raise typer.Exit(code=1)


@app.command()
def upload():
    """
    Upload a YAML file to the API. (Not supported yet)
    """
    typer.echo(red("Action not supported yet"))
    raise typer.Exit(code=1)
