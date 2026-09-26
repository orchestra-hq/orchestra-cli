"""The ``orchestra login`` token cache at ``~/.orchestra/credentials.json``.

Entries are keyed by Orchestra host so a login against staging (via ``BASE_URL``)
never sends its token to production, or vice versa.
"""

import json
import os
from pathlib import Path

from .constants import get_base_url


def credentials_path() -> Path:
    return Path.home() / ".orchestra" / "credentials.json"


def _read_all() -> dict:
    try:
        return json.loads(credentials_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_credentials() -> dict | None:
    return _read_all().get(get_base_url())


def save_credentials(credentials: dict) -> None:
    everything = {**_read_all(), get_base_url(): credentials}
    path = credentials_path()
    path.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    # The open's mode only applies to a new file; tighten an existing one before
    # any token is written to it.
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(everything, f, indent=2)
