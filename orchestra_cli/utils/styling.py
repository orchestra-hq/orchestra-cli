import typer


# Colors
def red(msg):
    return typer.style(msg, fg=typer.colors.RED, bold=True)


def green(msg):
    return typer.style(msg, fg=typer.colors.GREEN, bold=True)


def yellow(msg):
    return typer.style(msg, fg=typer.colors.YELLOW, bold=True)


def bold(msg):
    return typer.style(msg, bold=True)


def indent_message(msg: str, indent: str = "  ") -> str:
    return "\n".join(indent + line for line in msg.splitlines())
