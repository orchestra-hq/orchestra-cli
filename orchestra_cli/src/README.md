# orchestra_cli/src/

CLI command implementations. See `AGENTS.md` for conventions, patterns, and how to add new commands.

## Files

| File | Purpose |
|------|---------|
| `cli.py` | Typer app entry point; defines the `pipeline` sub-app and registers all verbs (plus hidden legacy aliases) |
| `validate_pipeline.py` | `orchestra pipeline validate` — validates a YAML against the API schema |
| `import_pipeline.py` | `orchestra pipeline import` — registers a pipeline from a git repo under an alias |
| `create_pipeline.py` | `orchestra pipeline new` — creates an Orchestra-backed pipeline from a local YAML |
| `update_pipeline.py` | `orchestra pipeline update` — updates an Orchestra-backed pipeline from a local YAML |
| `fetch_pipelines.py` | `orchestra pipeline get` — fetches pipelines visible to the current API key |
| `delete_pipeline.py` | `orchestra pipeline delete` — deletes a pipeline by alias |
| `run_pipeline.py` | `orchestra pipeline run` — starts a pipeline run; optionally polls until completion |

Each command module exports a single public function registered in `cli.py`.
