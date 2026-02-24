# AGENTS.md — orchestra_cli/src/

Command implementation guidance. See the root `AGENTS.md` for project overview, environment setup, running the CLI, and linting.

---

## Adding a New CLI Command

1. Create `orchestra_cli/src/<command_name>.py` with a single function decorated with Typer option/argument parameters.
2. Register it in `orchestra_cli/src/cli.py`:
   ```python
   from .<command_name> import <function_name>
   app.command(name="<command_name>")(<function_name>)
   ```
3. Add a corresponding `orchestra_cli/tests/test_<command_name>.py`.

---

## Patterns & Conventions

**Error handling:** All commands use `typer.Exit(code=1)` for failures — no exceptions propagate to the user. HTTP errors are caught with `try/except Exception` and printed via styled `typer.echo`.

**No models/schemas:** Data is passed directly as plain `dict` to `httpx` and parsed from JSON responses with `.get()`. Do not introduce Pydantic or dataclasses.

**Output styling:** All user-facing strings pass through helpers in `orchestra_cli/utils/styling.py`:
- `red(msg)` — errors
- `green(msg)` — success
- `yellow(msg)` — warnings / informational
- `bold(msg)` — emphasis
- `indent_message(msg)` — indents multi-line strings with two spaces

**Import style:** Use relative imports within `src/`:
```python
from ..utils.constants import get_api_url
from ..utils.styling import red, green
from ..utils.git import detect_repo_root
```

**Naming conventions:**
- Files: `snake_case.py`
- Functions/variables: `snake_case`
- Classes (rare): `PascalCase`
- Constants: `UPPER_SNAKE_CASE`

**New utility:** If logic is shared across ≥2 commands, add it to `orchestra_cli/utils/`. Keep command-private logic inside the command module.
