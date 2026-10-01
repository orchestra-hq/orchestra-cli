"""The ``orchestra login`` token cache at ``~/.orchestra/credentials.json``.

Entries are keyed by Orchestra host so a login against staging (via ``BASE_URL``)
never sends its token to production, or vice versa.
"""

import json
import os
import tempfile
from pathlib import Path

from .constants import get_base_url


def credentials_path() -> Path:
    return Path.home() / ".orchestra" / "credentials.json"


def _read_all() -> dict:
    try:
        everything = json.loads(credentials_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return everything if isinstance(everything, dict) else {}


def load_credentials() -> dict | None:
    return _read_all().get(get_base_url())


def save_credentials(credentials: dict) -> None:
    _write_all({**_read_all(), get_base_url(): credentials})


def clear_credentials() -> None:
    everything = _read_all()
    everything.pop(get_base_url(), None)
    _write_all(everything)


def _write_all(everything: dict) -> None:
    path = credentials_path()
    path.parent.mkdir(mode=0o700, exist_ok=True)
    # Written to a fresh 0600 file and swapped in, so a concurrent reader never sees a
    # half-written cache and the tokens are never readable by other users.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.")
    with os.fdopen(fd, "w") as f:
        json.dump(everything, f, indent=2)
    os.replace(tmp, path)
