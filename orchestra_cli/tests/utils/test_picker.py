import pytest

from orchestra_cli.utils.picker import pick
from tests.conftest import press_keys

UP = "\x1b[A"
DOWN = "\x1b[B"
ENTER = "\r"
ESC = "\x1b"


@pytest.mark.parametrize(
    ("keys", "start", "chosen"),
    [
        ((ENTER,), 0, 0),
        ((ENTER,), 2, 2),
        ((DOWN, ENTER), 0, 1),
        ((DOWN, DOWN, UP, ENTER), 0, 1),
        ((UP, ENTER), 0, 2),
        ((DOWN, ENTER), 2, 0),
        (("\xe0P", "\x1bOB", "\n"), 0, 2),
        (("x", DOWN, ENTER), 0, 1),
    ],
)
def test_pick_moves_wraps_and_selects(monkeypatch, keys, start, chosen):
    press_keys(monkeypatch, *keys)

    assert pick(["a", "b", "c"], start) == chosen


@pytest.mark.parametrize("cancel", [ESC, "\x03", "\x04"])
def test_pick_cancels(monkeypatch, cancel):
    press_keys(monkeypatch, DOWN, cancel)

    assert pick(["a", "b", "c"]) is None
