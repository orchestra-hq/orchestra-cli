# AGENTS.md — orchestra_cli/tests/

Test infrastructure and patterns. See root `AGENTS.md` for project overview, environment setup, and linting.

---

## Running Tests

```bash
# Run all tests
uv run pytest
# or via Makefile
make unit

# Run a specific test file
uv run pytest orchestra_cli/tests/test_run_pipeline.py

# Run a specific test by name
uv run pytest orchestra_cli/tests/test_run_pipeline.py::test_run_wait_success

# Run with verbose output
uv run pytest -v orchestra_cli/tests/
```

CI runs: `uv run pytest orchestra_cli/tests/`

---

## Test Infrastructure

**`conftest.py`** — `make_git_subprocess_mock(mapping)` factory; returns a `subprocess.run` drop-in that maps git subcommand tuples to `(returncode, stdout, stderr)`.

**`pytest-httpx`** — `HTTPXMock` fixture intercepts all `httpx` calls; used in all integration-style tests. Never make real network calls in tests.

**`typer.testing.CliRunner`** — used in every test file to invoke CLI commands without spawning a subprocess.

**`monkeypatch.setenv("ORCHESTRA_API_KEY", ...)`** — set in `autouse` fixtures in test files that need API auth.

No test markers (`@pytest.mark.*`) are defined beyond the standard set.

---

## Import Style

Use absolute imports in test files:

```python
from orchestra_cli.src.cli import app
from orchestra_cli.src.run_pipeline import run_pipeline
from tests.conftest import make_git_subprocess_mock
```

---

## Gotchas

**Polling / long-running behavior:** `run_pipeline.py` contains a `while True` loop with `time.sleep(5)`. Always mock sleep in tests that exercise the wait path:

```python
monkeypatch.setattr(time, "sleep", lambda _: None)
```
