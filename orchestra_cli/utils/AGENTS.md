# AGENTS.md — orchestra_cli/utils/

Shared utility modules. See root `AGENTS.md` for project overview. See `../src/AGENTS.md` for when to add logic here vs. keeping it in a command module.

---

## Modules

**`constants.py`** — API URL resolution:

```python
get_api_url("schema")      # → https://app.getorchestra.io/api/engine/public/pipelines/schema
get_api_url("demo/start")  # → https://app.getorchestra.io/api/engine/public/pipelines/demo/start
```

Override the base via the `BASE_URL` env var — it must contain a `{}` placeholder.

**`git.py`** — Git subprocess helpers:

- `run_git_command(args, cwd)` — thin wrapper around `subprocess.run(["git", *args], ...)`; returns `(ok: bool, output: str)`
- `detect_repo_root(path)` — walks up via `git rev-parse --show-toplevel`
- `git_warnings(repo_root)` — returns a list of human-readable warning strings

**`styling.py`** — Output formatting wrappers around `typer.style`:

- `red(msg)` — errors
- `green(msg)` — success
- `yellow(msg)` — warnings / informational
- `bold(msg)` — emphasis
- `indent_message(msg)` — indents multi-line strings with two spaces

---

## When to Add a New Utility

- Add to `utils/` if the logic is shared across ≥2 command modules.
- Keep command-private logic inside the command module itself.
