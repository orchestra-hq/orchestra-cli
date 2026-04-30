import typer

from .create_pipeline import create_pipeline
from .delete_pipeline import delete_pipeline
from .fetch_pipelines import fetch_pipelines
from .import_pipeline import import_pipeline
from .run_pipeline import run_pipeline
from .update_pipeline import update_pipeline
from .validate_pipeline import validate

app = typer.Typer(help="Orchestra CLI – perform operations with Orchestra locally.")

pipeline_app = typer.Typer(help="Manage Orchestra pipelines (validate, import, run, ...).")
app.add_typer(pipeline_app, name="pipeline")

pipeline_app.command(name="validate")(validate)
pipeline_app.command(name="import")(import_pipeline)
pipeline_app.command(name="new")(create_pipeline)
pipeline_app.command(name="update")(update_pipeline)
pipeline_app.command(name="get")(fetch_pipelines)
pipeline_app.command(name="run")(run_pipeline)
pipeline_app.command(name="delete")(delete_pipeline)

# Legacy top-level aliases (hidden) - keep the old `orchestra <command>` syntax working
# so existing scripts and CI pipelines do not break. Hidden from `--help` to keep the
# advertised surface focused on the new noun/verb structure.
app.command(name="validate", hidden=True)(validate)
app.command(name="import", hidden=True)(import_pipeline)
app.command(name="run", hidden=True)(run_pipeline)
app.command(name="fetch-pipelines", hidden=True)(fetch_pipelines)
app.command(name="create-pipeline", hidden=True)(create_pipeline)
app.command(name="update-pipeline", hidden=True)(update_pipeline)
app.command(name="delete-pipeline", hidden=True)(delete_pipeline)
