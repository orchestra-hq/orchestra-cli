# orchestra_cli/utils/

Shared utilities consumed by command modules in `../src/`. See `AGENTS.md` for module API reference and when to add logic here.

## Files

| File | Purpose |
|------|---------|
| `constants.py` | API URL resolution (`get_api_url`) |
| `git.py` | Git subprocess helpers (repo root detection, warnings) |
| `styling.py` | `typer.style` wrappers (`red`, `green`, `yellow`, `bold`, `indent_message`) |

`utils/` is a namespace package (no `__init__.py`). Import modules directly:

```python
# from within src/ (relative)
from ..utils.constants import get_api_url

# from tests/ (absolute)
from orchestra_cli.utils.git import detect_repo_root
```
