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

**`api.py`** — Shared HTTP/auth helpers. Every command should call into these instead of constructing headers, try/except blocks, or error rendering by hand:

- `require_api_key()` — returns `ORCHESTRA_API_KEY` from the environment, or echoes `"ORCHESTRA_API_KEY is not set"` and exits with code 1.
- `auth_headers(api_key)` — returns `{"Authorization": f"Bearer {api_key}"}`.
- `request_or_exit(httpx_func, *args, **kwargs)` — invokes an `httpx` callable (e.g. `httpx.post`, `httpx.delete`) and on any transport exception echoes `"HTTP request failed: <msg>"` in red and exits with code 1.
- `echo_response_error_body(response)` — echoes the response body as indented JSON when possible, falling back to plain text.
- `fail_with_response(action, response)` — echoes `"❌ <action> failed with status <code>"` followed by `echo_response_error_body(response)` and exits with code 1. Use this for any non-success path of an HTTP call.

**`yaml_loader.py`** — YAML loading + schema validation:

- `load_yaml(path)` — returns `(data, None)` on success or `(None, error_message)`.
- `validate_yaml_with_api(data)` — POSTs to the `schema` endpoint; returns `(ok, err_message)`.
- `load_validated_pipeline_data(path)` — convenience wrapper that loads, validates, and exits cleanly on any failure. Used by every command that takes a `--path` to a YAML file.

---

## When to Add a New Utility

- Add to `utils/` if the logic is shared across ≥2 command modules.
- Keep command-private logic inside the command module itself.
