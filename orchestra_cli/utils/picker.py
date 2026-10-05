import click
from rich.live import Live
from rich.text import Text

# Unix terminals send CSI or SS3 sequences; click.getchar on Windows returns a
# "\x00" or "\xe0" prefix followed by the scan code.
UP_KEYS = {"\x1b[A", "\x1bOA", "\x00H", "\xe0H"}
DOWN_KEYS = {"\x1b[B", "\x1bOB", "\x00P", "\xe0P"}
ENTER_KEYS = {"\r", "\n"}
ESCAPE = "\x1b"


def pick(labels: list[str], start: int = 0) -> int | None:
    """Let the user choose one of ``labels`` (not empty) with the arrow keys; return its index.

    Returns None when they press Esc, Ctrl+C or Ctrl+D. It needs an interactive
    terminal, so callers check that stdin and stdout are one first.
    """
    index = start
    with Live(auto_refresh=False, transient=True) as live:
        while True:
            live.update(_render(labels, index, live.console.height), refresh=True)
            try:
                key = click.getchar()
            except (KeyboardInterrupt, EOFError):
                return None
            if key in ENTER_KEYS:
                return index
            if key == ESCAPE:
                return None
            if key in UP_KEYS:
                index = (index - 1) % len(labels)
            elif key in DOWN_KEYS:
                index = (index + 1) % len(labels)


def _render(labels: list[str], index: int, height: int) -> Text:
    # Show only the rows that fit, keeping the selection in view, so it never
    # moves onto a row the terminal has cut off.
    rows = max(height - 1, 1)
    top = max(min(index - rows // 2, len(labels) - rows), 0)
    text = Text()
    for i, label in enumerate(labels[top : top + rows], start=top):
        if i == index:
            text.append(f"❯ {label}\n", style="bold cyan")
        else:
            text.append(f"  {label}\n")
    text.append("↑/↓ to move, Enter to select, Esc to cancel", style="dim")
    return text
