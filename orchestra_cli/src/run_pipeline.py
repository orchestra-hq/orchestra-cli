import typer

from ..utils.styling import red

app = typer.Typer()


@app.command()
def run_pipeline():
    """
    Run a pipeline in Orchestra. (🚧 Coming soon)
    """
    typer.echo(red("🚧 Action not supported yet"))
    raise typer.Exit(code=1)
