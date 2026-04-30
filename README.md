# orchestra-cli

Orchestra CLI for working with Orchestra pipelines from your terminal.

Two entrypoints are available: `orchestra` and `orchestra-cli` (they are equivalent).

See [`AGENTS.md`](AGENTS.md) for contributor and AI agent guidance (environment setup, code conventions, testing).

## Installation

```bash
pip install orchestra-cli
```

Or with pipx:

```bash
pipx install orchestra-cli
```

## Environment variables

- `ORCHESTRA_API_KEY`: Required for actions that call the API (`pipeline import`, `pipeline new`, `pipeline update`, `pipeline delete`, `pipeline run`).
- `BASE_URL`: Optional. Override the default Orchestra host (`https://app.getorchestra.io`) for non‑production/testing.

## Command structure

Commands follow a `noun verb` shape. The current noun is `pipeline`:

| Command | Description |
|---|---|
| `orchestra pipeline validate <file>` | Validate a pipeline YAML locally against the Orchestra API schema. |
| `orchestra pipeline import` | Register a pipeline YAML (from a git repo) with Orchestra under an alias. |
| `orchestra pipeline get` | Fetch the pipelines visible to the current API key as JSON. |
| `orchestra pipeline new` | Create an Orchestra-backed pipeline from a local YAML file. |
| `orchestra pipeline update` | Update an existing Orchestra-backed pipeline from a local YAML file. |
| `orchestra pipeline delete` | Delete an existing pipeline by alias. |
| `orchestra pipeline run` | Start a pipeline run by alias, optionally pinning branch/commit and waiting for completion. |

Use `orchestra --help`, `orchestra pipeline --help`, or `orchestra pipeline <verb> --help` for built-in help.

### Legacy command names

The previous flat command names continue to work as hidden top-level aliases so existing scripts keep running:

| Legacy alias | New canonical form |
|---|---|
| `orchestra validate` | `orchestra pipeline validate` |
| `orchestra import` | `orchestra pipeline import` |
| `orchestra fetch-pipelines` | `orchestra pipeline get` |
| `orchestra create-pipeline` | `orchestra pipeline new` |
| `orchestra update-pipeline` | `orchestra pipeline update` |
| `orchestra delete-pipeline` | `orchestra pipeline delete` |
| `orchestra run` | `orchestra pipeline run` |

New code and documentation should prefer the noun/verb form.

---

## pipeline validate

Validate a YAML file against the Orchestra API schema.

```bash
orchestra pipeline validate path/to/pipeline.yaml
# or
orchestra-cli pipeline validate path/to/pipeline.yaml
```

Options

- `file` (positional): Path to the YAML file to validate.

Behavior

- Prints a success message on valid input.
- On validation errors, prints the failing location(s), readable messages, and a YAML snippet when possible.
- Exit codes: `0` on success, `1` on invalid file/validation failure/HTTP error.

Example output (failure)

```text
❌ Validation failed with status 422
Error at: pipeline.tasks[0].type
  Invalid task type "foo"

YAML snippet:
pipeline:
  tasks:
    - type: foo
```

---

## pipeline import

Create (import) a pipeline in Orchestra by referencing a YAML file inside a git repository. The command infers your repository host/provider, default branch, and YAML path relative to the repo root.

```bash
export ORCHESTRA_API_KEY=...  # required

orchestra pipeline import \
  --alias my-pipeline \
  --path ./pipelines/pipeline.yaml \
  --working-branch my-feature-branch   # optional; defaults to current local branch
# or
orchestra-cli pipeline import -a my-pipeline -p ./pipelines/pipeline.yaml
```

Options

- `-a, --alias` (required): The alias you want to register the pipeline under.
- `-p, --path` (required): Path to the YAML file. Must be inside a git repository.
- `-w, --working-branch` (optional): Branch to associate as the working branch for this pipeline import. If omitted, the current local git branch is used.

Notes

- The YAML is validated with the API before import; failures are printed clearly.
- Git details are detected automatically:
  - Supported providers: GitHub, GitLab, Azure DevOps.
  - The default branch is detected from `origin`.
  - The working branch defaults to your current local branch when not specified.
  - The YAML path is computed relative to the repository root.
- On success, the command prints the created pipeline ID (or a success message).
- Exit codes: `0` on success, `1` on failure.

Common errors

- Missing `ORCHESTRA_API_KEY`.
- Not running inside a git repository, or no `origin` remote configured.
- Could not detect storage provider or default branch.

---

## pipeline new

Create an Orchestra-backed pipeline directly from a local YAML file.

```bash
export ORCHESTRA_API_KEY=...

orchestra pipeline new \
  --alias my-pipeline \
  --path ./pipelines/pipeline.yaml \
  --publish            # optional, defaults to --no-publish
```

Options

- `-a, --alias` (required): Pipeline alias.
- `-p, --path` (required): Path to pipeline YAML file.
- `--publish/--no-publish` (optional, default `--no-publish`): Whether the pipeline is published.

Behavior

- Validates YAML against the Orchestra schema endpoint before creating.
- Sends pipeline data to `POST /pipelines` with `storage_provider=ORCHESTRA`.
- On success, prints the pipeline edit URL (`/pipelines/{pipeline_id}/edit`) when an ID is returned.
- Exit codes: `0` on success, `1` on failure.

---

## pipeline get

Fetch the pipelines available to the current Orchestra API key.

```bash
export ORCHESTRA_API_KEY=...

orchestra pipeline get
```

Behavior

- Sends `GET /api/engine/public/pipelines`. Responses always include each pipeline's latest run metadata.
- Prints the response payload as pretty JSON for scripting and inspection.
- Exit codes: `0` on success, `1` on failure.

---

## pipeline update

Update an existing Orchestra-backed pipeline from a local YAML file.

```bash
export ORCHESTRA_API_KEY=...

orchestra pipeline update \
  --alias my-pipeline \
  --path ./pipelines/pipeline.yaml \
  --no-publish         # default
```

Options

- `-a, --alias` (required): Pipeline alias to update.
- `-p, --path` (required): Path to pipeline YAML file.
- `--publish/--no-publish` (optional, default `--no-publish`): Whether the pipeline is published.

Behavior

- Validates YAML against the Orchestra schema endpoint before updating.
- Sends pipeline data to `PUT /pipelines/{alias}` with `storage_provider=ORCHESTRA`.
- Only Orchestra-backed pipelines can be updated via this endpoint (Git-backed pipelines are rejected).
- On success, prints the pipeline edit URL (`/pipelines/{pipeline_id}/edit`) when an ID is returned.
- Exit codes: `0` on success, `1` on failure.

---

## pipeline delete

Delete a pipeline by alias.

```bash
export ORCHESTRA_API_KEY=...

orchestra pipeline delete --alias my-pipeline
```

Options

- `-a, --alias` (required): Pipeline alias to delete.

Behavior

- Sends `DELETE /pipelines/{alias}` with API key authentication.
- Deletes the pipeline resolved by alias within the authenticated account.
- On success, exits with code `0` after printing a confirmation message.
- Exit codes: `0` on success, `1` on failure.

---

## pipeline run

Start a pipeline run by alias. Optionally specify a branch and/or commit. By default, the command waits and polls the run status until completion.

```bash
export ORCHESTRA_API_KEY=...

# Start and wait for completion
orchestra pipeline run --alias my-pipeline

# Start without waiting (prints run id and exits)
orchestra pipeline run -a my-pipeline --no-wait

# Start for a specific branch/commit
orchestra pipeline run -a my-pipeline -b feature/my-change -c 0123abc
```

Options

- `-a, --alias` (required): Pipeline alias to run.
- `-b, --branch` (optional): Git branch name to associate with this run.
- `-c, --commit` (optional): Commit SHA to associate with this run.
- `--wait/--no-wait` (default: `--wait`): Poll until the run ends.
- `--force/--no-force` (default: `--no-force`): Skip confirmation if local git warnings are detected.

Behavior

- Prints the run ID when known and a link to the run lineage page.
- When waiting, polls status every ~5s until a terminal state:
  - `SUCCEEDED` (exit `0`), `WARNING` (exit `0`), `SKIPPED` (exit `0`)
  - `FAILED` or `CANCELLED` (exit `1`)
- When not waiting, exits after start and prints the run ID.

Non-interactive usage

- If your repo has warnings (e.g., uncommitted changes), the CLI prompts for confirmation unless `--force` is provided. For CI or scripts, pass `--force` or ensure a clean repo.

---

## Examples

```bash
# Validate a pipeline file
orchestra pipeline validate ./examples/etl.yaml

# Import a pipeline and capture the created ID
PIPELINE_ID=$(orchestra pipeline import -a finance-etl -p ./pipelines/etl.yaml)

# Start a run and wait for completion
orchestra pipeline run -a finance-etl

# Start a run and exit immediately
orchestra pipeline run -a finance-etl --no-wait
```

---

## Development

- Make sure [uv](https://github.com/astral-sh/uv) is installed
- Use `uv pip install -e ".[dev]"` to install the CLI in editable mode for development
- For local development, run `uv run orchestra` to start the CLI
  - you can use `uv run --env-file .env ...` to run the CLI with env vars
- For testing, run `uv run pytest`
- For linting, run `uv run ruff check .`
- For formatting, run `uv run black --check .`
- For type checking, run `uv run pyright`

## Building and Releasing

- Bump the version in `pyproject.toml` or by running `uv version --bump <major/minor/patch>`
- Run `uv sync` to install the dependencies
- Run `uv build` to build the CLI
- Run `uv publish` to publish the CLI (you will need to pass the `--token` flag)

**Note: Failure to bump the version will result in a failed release.**
