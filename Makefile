install:
	uv sync

install-dev:
	uv sync --group dev

lint:
	uv run ruff check .
	uv run pyright
	uv run black --check .

unit:
	uv run pytest

test: lint unit

build:
	uv build

publish:
	uv publish