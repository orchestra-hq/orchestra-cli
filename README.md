# orchestra-cli

Orchestra CLI for working with Orchestra pipelines from your terminal.

Two entrypoints are available: `orchestra` and `orchestra-cli` (they are equivalent).

## Installation

```bash
pip install orchestra-cli
```

Or with pipx:

```bash
pipx install orchestra-cli
```

## Environment variables

- `ORCHESTRA_API_KEY`: Required for actions that call the API (`import`, `run`).
- `BASE_URL`: Optional. Override the default API base
  (`https://app.getorchestra.io/api/engine/public/pipelines/{}`) for non‑production/testing.

## Commands overview

- `validate`: Validate a pipeline YAML locally against the Orchestra API schema.
- `import`: Register a pipeline YAML (from a git repo) with Orchestra under an alias.
- `run`: Start a pipeline run by alias, optionally pinning branch/commit and waiting for completion.

Use `orchestra --help` or `orchestra <command> --help` for built-in help.

---

## validate

Validate a YAML file against the Orchestra API schema.

```bash
orchestra validate path/to/pipeline.yaml
# or
orchestra-cli validate path/to/pipeline.yaml
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

## import

Create (import) a pipeline in Orchestra by referencing a YAML file inside a git repository. The command infers your repository host/provider, default branch, and YAML path relative to the repo root.

```bash
export ORCHESTRA_API_KEY=...  # required

orchestra import \
  --alias my-pipeline \
  --path ./pipelines/pipeline.yaml \
  --working-branch my-feature-branch   # optional; defaults to current local branch
# or
orchestra-cli import -a my-pipeline -p ./pipelines/pipeline.yaml
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

## run

Start a pipeline run by alias. Optionally specify a branch and/or commit. By default, the command waits and polls the run status until completion.

```bash
export ORCHESTRA_API_KEY=...

# Start and wait for completion
orchestra run --alias my-pipeline

# Start without waiting (prints run id and exits)
orchestra run -a my-pipeline --no-wait

# Start for a specific branch/commit
orchestra run -a my-pipeline -b feature/my-change -c 0123abc
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
orchestra validate ./examples/etl.yaml

# Import a pipeline and capture the created ID
PIPELINE_ID=$(orchestra import -a finance-etl -p ./pipelines/etl.yaml)

# Start a run and wait for completion
orchestra run -a finance-etl

# Start a run and exit immediately
orchestra run -a finance-etl --no-wait
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
