import click
import pytest
from pytest_httpx import HTTPXMock

STATUS_CLASSIFICATIONS_URL = "https://app.getorchestra.io/api/engine/public/status_classifications/"

# Pipeline run statuses as /status_classifications/ serves them, with their classifications.
PIPELINE_RUN_CLASSIFICATIONS = {
    "QUEUED": ["cancellable"],
    "CREATED": ["cancellable"],
    "RUNNING": ["cancellable"],
    "SUCCEEDED": ["completed", "successful", "triggerable"],
    "WARNING": ["completed", "successful", "triggerable"],
    "FAILED": ["completed", "triggerable"],
    "SKIPPED": ["completed"],
    "CANCELLING": ["force_cancellable"],
    "CANCELLED": ["completed", "triggerable"],
}


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


def status_classifications_body(
    pipeline_run: dict[str, list[str]] = PIPELINE_RUN_CLASSIFICATIONS,
) -> list[dict[str, object]]:
    """A /status_classifications/ response serving ``pipeline_run``'s statuses."""
    return [
        {
            "name": "task_run",
            "members": [{"value": "RUNNING", "classifications": ["cancellable"]}],
        },
        {
            "name": "pipeline_run",
            "members": [
                {"value": value, "classifications": classifications}
                for value, classifications in pipeline_run.items()
            ],
        },
    ]


@pytest.fixture
def served_status_classifications(httpx_mock: HTTPXMock) -> None:
    """Serve the run status classifications to any command that waits on a run."""
    httpx_mock.add_response(
        method="GET",
        url=STATUS_CLASSIFICATIONS_URL,
        json=status_classifications_body(),
        is_optional=True,
        is_reusable=True,
    )
