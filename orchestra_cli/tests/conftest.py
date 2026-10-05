import click
import pytest


def make_git_subprocess_mock(mapping: dict[tuple[str, ...], tuple[int, str, str]]):
    class Result:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _mock_run(args, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        # args begins with ["git", ...]
        key = tuple(args[1:])
        rc, out, err = mapping.get(key, (1, "", ""))
        return Result(rc, out, err)

    return _mock_run


def press_keys(monkeypatch, *keys: str):
    """Make ``click.getchar`` return ``keys`` in order, raising on Ctrl+C/D as click does."""
    pending = list(keys)

    def getchar():
        key = pending.pop(0)
        if key == "\x03":
            raise KeyboardInterrupt
        if key == "\x04":
            raise EOFError
        return key

    monkeypatch.setattr(click, "getchar", getchar)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    # Keeps tests off the developer's real ~/.orchestra login cache.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path
