import typer

from .create_pipeline import create_pipeline
from .import_pipeline import import_pipeline
from .run_pipeline import run_pipeline
from .update_pipeline import update_pipeline
from .validate_pipeline import validate

app = typer.Typer(help="Orchestra CLI – perform operations with Orchestra locally.")


app.command(name="validate")(validate)
app.command(name="import")(import_pipeline)
app.command(name="run")(run_pipeline)
app.command(name="create-pipeline")(create_pipeline)
app.command(name="update-pipeline")(update_pipeline)
