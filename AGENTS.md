# AGENTS.md — orchestra-cli

## 1. Project Overview

`orchestra-cli` is a Python CLI tool for interacting with Orchestra pipeline orchestration from the terminal — it validates, imports, and runs Orchestra pipelines defined as YAML files.

- **Language/runtime:** Python 3.12 (pinned in `.python-version`)
- **Framework:** [Typer](https://typer.tiangolo.com/) for CLI; [httpx](https://www.python-httpx.org/) for HTTP; [PyYAML](https://pyyaml.org/) for YAML parsing
- **Packaging/dependency manager:** [uv](https://github.com/astral-sh/uv) with `pyproject.toml`
- **Architectural pattern:** Flat command-per-file — each CLI command is its own module; utility helpers live in a separate `utils/` package

---

## 2. Repo Layout

```
orchestra-cli/
├── orchestra_cli/
│   ├── src/                    # CLI command implementations
│   │   ├── cli.py              # Typer app entry point; registers all commands
│   │   ├── validate_pipeline.py
│   │   ├── import_pipeline.py
│   │   └── run_pipeline.py
│   ├── tests/                  # pytest test suite
│   │   ├── conftest.py         # Shared test helpers (git subprocess mock factory)
│   │   ├── test_cli.py
│   │   ├── test_validate_pipeline.py
│   │   ├── test_import_pipeline.py
│   │   └── test_run_pipeline.py
│   └── utils/                  # Shared utilities (not commands)
│       ├── constants.py        # API URL resolution via BASE_URL env var
│       ├── git.py              # Git subprocess helpers (detect root, warnings, etc.)
│       └── styling.py          # typer.style color/bold wrappers
├── .github/
│   └── workflows/
│       ├── ci.yml              # PR lint + test pipeline
│       └── release.yml         # Build + publish to PyPI on push to main
├── pyproject.toml              # Project metadata, deps, ruff/black/pyright config
├── uv.lock                     # Locked dependency manifest (auto-generated, do not edit)
├── Makefile                    # Convenience targets: install, lint, unit, test, build, publish
├── valid.yaml                  # Example valid pipeline YAML (for manual testing)
└── invalid.yaml                # Example invalid pipeline YAML (for manual testing)
```

**Conventions:**
- Source lives under `orchestra_cli/src/` (not a `src/` layout at repo root).
- Tests import as `from tests.conftest import ...` — the repo root must be on `PYTHONPATH` (pytest handles this automatically).
- No `__init__.py` at the repo root; the package root is `orchestra_cli/`.

---

## 3. Environment Setup

```bash
# 1. Install uv (if not present)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install runtime + dev dependencies
uv sync --group dev

# 3. (Optional) install CLI in editable mode for interactive use
uv pip install -e ".[dev]"
```

**Environment variables:**

| Variable            | Required | Default                                                                 | Purpose                          |
|---------------------|----------|-------------------------------------------------------------------------|----------------------------------|
| `ORCHESTRA_API_KEY` | Yes*     | —                                                                       | Auth token for `import` and `run` |
| `BASE_URL`          | No       | `https://app.getorchestra.io/api/engine/public/pipelines/{}`            | Override API base (e.g., staging) |

*Required only for commands that call the API (`import`, `run`). `validate` does not need it.

Store secrets in a `.env` file (already in `.gitignore`):
```bash
echo "ORCHESTRA_API_KEY=your-key" > .env
```

No system-level dependencies beyond Python 3.12 and git (used at runtime by the `import` command to detect repo metadata).

---

## 4. Running the Project

```bash
# Run via uv (no install required)
uv run orchestra --help
uv run orchestra validate valid.yaml
uv run orchestra import --alias my-pipeline --path ./valid.yaml
uv run orchestra run --alias my-pipeline --no-wait

# With env vars from a .env file
uv run --env-file .env orchestra run --alias my-pipeline

# After editable install
orchestra --help
orchestra-cli --help   # equivalent alias
```

Both `orchestra` and `orchestra-cli` entry points map to `orchestra_cli.src.cli:app`.

---

## 5. Testing

See `orchestra_cli/tests/AGENTS.md` for test runner commands, infrastructure details, import conventions, and gotchas.

---

## 6. Code Style & Linting

All tools are run through `uv run` or via `make lint` / `make test`.

| Tool      | Command                          | Config location      |
|-----------|----------------------------------|----------------------|
| **black** | `uv run black --check .`         | `[tool.black]` in `pyproject.toml` — line length 100, excludes `.venv` |
| **ruff**  | `uv run ruff check .`            | `[tool.ruff]` in `pyproject.toml` — selects E, F, W, I, N, UP, ARG, COM rules |
| **pyright** | `uv run pyright`               | `[tool.pyright]` in `pyproject.toml` — `typeCheckingMode = "basic"` |

```bash
# Auto-format
uv run black .

# Auto-fix lint issues
uv run ruff check --fix .

# Type check
uv run pyright

# Run all checks (lint + tests)
make test
```

No pre-commit hooks are configured.

---

## 7. Common Patterns & Conventions

See `orchestra_cli/src/AGENTS.md` for error handling, output styling, import style, and naming conventions.

See `orchestra_cli/utils/AGENTS.md` for utility module reference (`constants.py`, `git.py`, `styling.py`).

---

## 8. Adding New Code

See `orchestra_cli/src/AGENTS.md` for step-by-step instructions on adding a new CLI command or utility.

---

## 10. Agent-Specific Guidance

**Never edit directly:**
- `uv.lock` — auto-generated by `uv sync`; update by running `uv sync` or `uv add <pkg>`

**Auto-generated / do not touch:**
- `*.egg-info/` directories
- `__pycache__/` directories
- `.venv/`

**Safe to run freely:**
```bash
uv run pytest                       # fast, no network, no side effects
uv run ruff check .                 # read-only lint
uv run black --check .              # read-only format check
uv run pyright                      # type checking
uv run orchestra validate <file>    # calls the Orchestra API (schema endpoint, no auth required)
```

**Requires caution:**
```bash
uv run orchestra import ...         # creates a pipeline in the Orchestra backend (requires API key)
uv run orchestra run ...            # starts a live pipeline run (requires API key, has polling loop)
uv build                            # builds a distributable package
uv publish                          # publishes to PyPI — only run intentionally with correct version
make publish                        # same as uv publish
```

**Verifying a change end-to-end:**
1. `make lint` — ruff + pyright + black all pass
2. `make unit` — all pytest tests pass
3. For a new command, confirm `uv run orchestra <command> --help` shows the expected options
4. For HTTP-touching changes, add/update tests using `HTTPXMock` to intercept calls; avoid real network calls in tests
5. For git-detection changes, use `make_git_subprocess_mock` from `conftest.py` to simulate git output

