# orchestra_cli/tests/

Test suite for all CLI commands. See `AGENTS.md` for runner commands, test infrastructure, import conventions, and gotchas.

## Files

| File | Covers |
|------|--------|
| `conftest.py` | `make_git_subprocess_mock` factory — shared across tests that exercise git detection |
| `test_cli.py` | Top-level app registration and help output |
| `test_validate_pipeline.py` | Schema validation, error formatting, exit codes |
| `test_import_pipeline.py` | Git detection, API call, option handling, missing auth |
| `test_run_pipeline.py` | Run start, polling loop, terminal states, `--no-wait`, `--force` |

## Test naming

Tests follow the pattern `test_<command>_<scenario>`, e.g. `test_run_wait_success`, `test_import_missing_api_key`.
