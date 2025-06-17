# orchestra-cli

A Python-based CLI tool for running Orchestra actions.

## Example

```bash
orchestra-cli validate example.yaml
```

## Development

- Make sure [uv](https://github.com/astral-sh/uv) is installed
- Use `uv pip install -e ".[dev]"` to install the CLI in editable mode for development

## Building and Releasing

- Run `uv build` to build the CLI
- Run `uv publish` to publish the CLI (you will need to pass the `--token` flag)
