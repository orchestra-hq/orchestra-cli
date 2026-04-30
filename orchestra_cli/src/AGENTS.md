# AGENTS.md — orchestra_cli/src/

Command implementation guidance. See the root `AGENTS.md` for project overview, environment setup, running the CLI, and linting.

---

## CLI Structure

The CLI is organised as `orchestra <noun> <verb>`. The only noun today is `pipeline`, exposed as a Typer sub-app (`pipeline_app`) attached to the root `app` in `cli.py`. Verbs (`validate`, `import`, `new`, `update`, `get`, `delete`, `run`) are registered on `pipeline_app`.

The previous flat command names (`validate`, `import`, `run`, `fetch-pipelines`, `create-pipeline`, `update-pipeline`, `delete-pipeline`) are also registered on the root `app` as **hidden** aliases (`hidden=True`) so existing scripts keep working. They do not appear in `--help` output.

## Adding a New CLI Command

1. Create `orchestra_cli/src/<command_name>.py` with a single function decorated with Typer option/argument parameters.
2. Register it on the appropriate sub-app in `orchestra_cli/src/cli.py`:

   ```python
   from .<command_name> import <function_name>
   pipeline_app.command(name="<verb>")(<function_name>)
   ```

   If the command does not belong to an existing noun, add a new `typer.Typer()` sub-app and `app.add_typer(...)` it under the appropriate noun.

3. If you need to preserve a legacy flat name, add a hidden top-level alias:

   ```python
   app.command(name="<legacy-name>", hidden=True)(<function_name>)
   ```

4. Add a corresponding `orchestra_cli/tests/test_<command_name>.py`.

---

## Patterns & Conventions

**Error handling:** All commands use `typer.Exit(code=1)` for failures — no exceptions propagate to the user. Use the helpers in `orchestra_cli/utils/api.py` for the common patterns rather than rolling your own:

- `require_api_key()` — resolves `ORCHESTRA_API_KEY` or exits.
- `request_or_exit(httpx.<method>, url, ...)` — wraps the request in a uniform transport-error handler.
- `fail_with_response("Action", response)` — uniform `❌ Action failed with status <code>` output for non-success HTTP responses.
- `auth_headers(api_key)` — builds the `Authorization` header.

**YAML loading:** Commands that take a `--path` to a pipeline YAML should use `load_validated_pipeline_data(path)` from `orchestra_cli/utils/yaml_loader.py` — it loads, schema-validates against the API, and exits cleanly on any failure.

**No models/schemas:** Data is passed directly as plain `dict` to `httpx` and parsed from JSON responses with `.get()`. Do not introduce Pydantic or dataclasses.

**Output styling:** All user-facing strings pass through helpers in `orchestra_cli/utils/styling.py`:

- `red(msg)` — errors
- `green(msg)` — success
- `yellow(msg)` — warnings / informational
- `bold(msg)` — emphasis
- `indent_message(msg)` — indents multi-line strings with two spaces

**Import style:** Use relative imports within `src/`:

```python
from ..utils.api import auth_headers, fail_with_response, request_or_exit, require_api_key
from ..utils.constants import get_api_url
from ..utils.styling import red, green
from ..utils.git import detect_repo_root
from ..utils.yaml_loader import load_validated_pipeline_data
```

**Naming conventions:**

- Files: `snake_case.py`
- Functions/variables: `snake_case`
- Classes (rare): `PascalCase`
- Constants: `UPPER_SNAKE_CASE`

**New utility:** If logic is shared across ≥2 commands, add it to `orchestra_cli/utils/`. Keep command-private logic inside the command module.
