# orchestra_cli/src/

CLI command implementations. See `AGENTS.md` for conventions, patterns, and how to add new commands.

## Files

| File | Purpose |
|------|---------|
| `cli.py` | Typer app entry point; registers all commands |
| `validate_pipeline.py` | `orchestra validate` — validates a YAML against the API schema |
| `import_pipeline.py` | `orchestra import` — registers a pipeline from a git repo under an alias |
| `run_pipeline.py` | `orchestra run` — starts a pipeline run; optionally polls until completion |

Each command module exports a single public function registered in `cli.py`.
