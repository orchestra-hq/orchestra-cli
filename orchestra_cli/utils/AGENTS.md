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

- `require_credential()` — returns the bearer credential: the cached `orchestra login` token (refreshed when near expiry) if there is a usable one, otherwise `ORCHESTRA_API_KEY`. Exits with code 1 if neither is available.
- `api_client(account_id=None, scoped=True)` — returns the `httpx.Client` (30s timeout) a command passes down to every helper that calls the API. Its auth sets `Authorization: Bearer <credential>` on each request, calling `require_credential()` each time so a long-running command never sends an expired login token, plus `X-Orchestra-Account-Id` from `account_id` or the login's saved `account_id` (`scoped=False` omits it). The client closes when the click command ends.
- `account_id_option()` — every workspace-scoped API command declares `account_id: str | None = account_id_option()` (`--account-id`, falling back to `ORCHESTRA_ACCOUNT_ID`) and passes it to `api_client()`.
- `request_or_exit(client_method, *args, **kwargs)` — invokes a client method (e.g. `client.post`, `client.delete`) and on any transport exception echoes `"HTTP request failed: <msg>"` in red and exits with code 1. A `typer.Exit` from the client's auth passes through untouched.
- `echo_response_error_body(response)` — echoes the response body as indented JSON when possible, falling back to plain text.
- `fail_with_response(action, response)` — echoes `"❌ <action> failed with status <code>"` followed by `echo_response_error_body(response)` and exits with code 1. Use this for any non-success path of an HTTP call.

**`accounts.py`** — `fetch_accounts(client)` returns the workspaces the current credential covers (`GET /public/v1/accounts`, `[{id, name}]`), exiting 1 on any failure. Callers pass `api_client(scoped=False)`, since the call isn't scoped to a workspace. `pick_account(accounts, default_id=None)` shows them in the picker and returns the chosen one, or `None` on cancel.

**`picker.py`** — `pick(labels, start=0)` shows an arrow-key menu (keys from `click.getchar()`, redrawn with `rich.live.Live`) and returns the chosen index, or `None` on Esc, Ctrl+C or Ctrl+D. Check `can_pick()` first: it is false without an interactive terminal on stdin and stdout (CI, pipes, `TERM=dumb`), where `pick` would wait for keys behind an invisible menu. Tests feed keys with `press_keys(monkeypatch, ...)` from `tests/conftest.py`.

**`credentials.py`** — the `orchestra login` token cache at `~/.orchestra/credentials.json`, keyed by host (`get_base_url()`). `load_credentials()` / `save_credentials(dict)` / `clear_credentials()`; writes are atomic and mode `0600`. Tests get an isolated `HOME` from an autouse fixture in `conftest.py`.

**`yaml_loader.py`** — YAML loading + schema validation:

- `exit_if_unsupported_extension(path)` — exits unless the file ends in `.yaml`, `.yml` or `.oml`.
- `echo_invalid_yaml(path, err)` — prints the `Invalid YAML` error, plus a hint about unsupported OML syntax for `.oml` files.
- `load_yaml(path)` — returns `(data, None)` on success or `(None, error_message)`.
- `validate_yaml_with_api(data)` — POSTs to the `schema` endpoint; returns `(ok, err_message)`.
- `load_validated_pipeline_data(path)` — convenience wrapper that checks the extension, loads, validates, and exits cleanly on any failure. Used by every command that takes a `--path` to a YAML file.

---

## When to Add a New Utility

- Add to `utils/` if the logic is shared across ≥2 command modules.
- Keep command-private logic inside the command module itself.
