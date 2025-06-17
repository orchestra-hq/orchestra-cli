import yaml
import httpx
import typer
from pathlib import Path

app = typer.Typer(help="Orchestra CLI – perform operations with Orchestra locally.")

API_URL = "https://httpstat.us/200"  # Replace with your real endpoint


# Colors
def red(msg):
    return typer.style(msg, fg=typer.colors.RED, bold=True)


def green(msg):
    return typer.style(msg, fg=typer.colors.GREEN, bold=True)


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
        typer.echo(red(f"❌ Validation failed with status {response.status_code}"))
        try:
            errors = response.json()
            typer.echo(yaml.dump(errors, sort_keys=False))
        except Exception:
            typer.echo(response.text)
        raise typer.Exit(code=1)


@app.command()
def upload(file: Path = typer.Argument(..., help="YAML file to upload")):
    """
    Upload a YAML file to the API. (Not supported yet)
    """
    typer.echo(red("Action not supported yet"))
    raise typer.Exit(code=1)
