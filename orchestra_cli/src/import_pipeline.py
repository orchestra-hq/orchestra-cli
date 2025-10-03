import typer

from ..utils.styling import red

app = typer.Typer()


@app.command()
def import_pipeline():
    """
    Upload a YAML file to the API. (🚧 Coming soon)
    """
    typer.echo(red("🚧 Action not supported yet"))
    raise typer.Exit(code=1)
