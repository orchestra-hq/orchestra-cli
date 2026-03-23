from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()

# YAML where a condition references a standalone task (no 'tasks' key) via task_groups[...]
YAML_BAD_TASK_GROUP_REF = """\
version: v1
name: test
pipeline:
  real_group:
    tasks:
      t1:
        integration: DBT_CORE
        integration_job: DBT_CORE_EXECUTE
        parameters: {}
        depends_on: []
    depends_on: []
    name: ''
  standalone_task:
    integration: ORCHESTRA
    integration_job: APPROVAL
    parameters: {}
    depends_on: []
    name: Approve
  consumer_group:
    tasks:
      t2:
        integration: PYTHON
        integration_job: PYTHON_EXECUTE_SCRIPT
        parameters: {}
        depends_on: []
        condition: "${{ task_groups['standalone_task'].any().status == 'SUCCEEDED' }}"
        name: bad ref in task condition
    depends_on:
    - standalone_task
    condition: "${{ task_groups['standalone_task'].any().status == 'SUCCEEDED' }}"
    name: ''
"""

# YAML where all task_groups[...] conditions reference real task groups
YAML_VALID_TASK_GROUP_REF = """\
version: v1
name: test
pipeline:
  real_group:
    tasks:
      t1:
        integration: DBT_CORE
        integration_job: DBT_CORE_EXECUTE
        parameters: {}
        depends_on: []
    depends_on: []
    name: ''
  consumer_group:
    tasks:
      t2:
        integration: PYTHON
        integration_job: PYTHON_EXECUTE_SCRIPT
        parameters: {}
        depends_on: []
        condition: "${{ task_groups['real_group'].any().status == 'SUCCEEDED' }}"
        name: valid ref in task condition
    depends_on:
    - real_group
    condition: "${{ task_groups['real_group'].any().status == 'SUCCEEDED' }}"
    name: ''
"""


def test_validate_missing_file():
    result = runner.invoke(app, ["validate", "not_a_file.yaml"])
    assert result.exit_code == 1
    assert "File not found" in result.output


def test_validate_bad_task_group_reference_fails_locally(tmp_path: Path):
    """A condition referencing a standalone task via task_groups[...] should fail
    before any API call is made."""
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text(YAML_BAD_TASK_GROUP_REF)

    result = runner.invoke(app, ["validate", str(yaml_file)])

    assert result.exit_code == 1
    assert "local check" in result.output
    assert "standalone_task" in result.output


def test_validate_valid_task_group_reference_passes_through(
    tmp_path: Path,
    httpx_mock: HTTPXMock,
):
    """When all task_groups[...] references point to real task groups the local
    check passes and the request reaches the API."""
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text(YAML_VALID_TASK_GROUP_REF)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )

    result = runner.invoke(app, ["validate", str(yaml_file)])

    assert result.exit_code == 0
    assert "Validation passed" in result.output


@pytest.mark.parametrize("yaml_content", ["name: test\nversion: v1\n", "{}"])
def test_validate_no_pipeline_key_passes_local_check(
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    yaml_content: str,
):
    """YAML without a pipeline key has nothing to cross-reference; the local
    check should pass through to the API."""
    yaml_file = tmp_path / "pipe.yaml"
    yaml_file.write_text(yaml_content)

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )

    result = runner.invoke(app, ["validate", str(yaml_file)])

    assert result.exit_code == 0
