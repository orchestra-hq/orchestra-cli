# orchestra_cli/src/

CLI command implementations. See `AGENTS.md` for conventions, patterns, and how to add new commands.

## Files

| File | Purpose |
|------|---------|
| `cli.py` | Typer app entry point; defines the `pipeline` sub-app and registers all verbs (plus hidden legacy aliases) |
| `validate_pipeline.py` | `orchestra pipeline validate` — validates a YAML against the API schema |
| `import_pipeline.py` | `orchestra pipeline import` — registers a pipeline from a git repo under an alias |
| `create_pipeline.py` | `orchestra pipeline new` — creates an Orchestra-backed pipeline from a local YAML |
| `update_pipeline.py` | `orchestra pipeline update` — updates a pipeline from local YAML (Orchestra-backed upsert or git-backed commit/push flow) |
| `get_pipeline.py` | `orchestra pipeline get` — fetches one pipeline by selector |
| `fetch_pipelines.py` | `orchestra pipeline list` — fetches pipelines visible to the current API key |
| `delete_pipeline.py` | `orchestra pipeline delete` — deletes a pipeline by alias |
| `build_pipeline.py` | `orchestra pipeline build` — validates local YAML, creates/updates a draft pipeline, and starts that draft version |
| `migrate_pipeline.py` | `orchestra pipeline migrate` — migrates an Orchestra-backed pipeline to git-backed storage |
| `run_pipeline.py` | `orchestra pipeline run` — starts a pipeline run; optionally polls until completion |

Each command module exports a single public function registered in `cli.py`.
