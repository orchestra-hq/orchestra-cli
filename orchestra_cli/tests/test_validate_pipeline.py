import json

from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from orchestra_cli.src.cli import app

runner = CliRunner()


def test_validate_missing_file():
    result = runner.invoke(app, ["pipeline", "validate", "not_a_file.yaml"])
    assert result.exit_code == 1
    assert "File not found" in result.output


def test_validate_success_posts_expected_json(tmp_path, httpx_mock: HTTPXMock):
    pipeline_file = tmp_path / "pipeline.yaml"
    pipeline_file.write_text(
        "\n".join(
            [
                "pipeline:",
                "  pre-daily:",
                "    TaskGroupModel:",
                "      tasks:",
                "        dbt-run-pre-daily:",
                "          task_type: dbt",
                "          connection: GCP_CLOUD_RUN",
            ],
        ),
    )
    expected_payload = {
        "pipeline": {
            "pre-daily": {
                "TaskGroupModel": {
                    "tasks": {
                        "dbt-run-pre-daily": {
                            "task_type": "dbt",
                            "connection": "GCP_CLOUD_RUN",
                        },
                    },
                },
            },
        },
    }

    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "validate", str(pipeline_file)])

    assert result.exit_code == 0
    assert "Validation passed" in result.output

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].url == "https://app.getorchestra.io/api/engine/public/pipelines/schema"
    assert json.loads(requests[0].content) == expected_payload


def test_validate_fails_on_duplicate_yaml_keys(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "\n".join(
            [
                "pipeline:",
                "  pre-daily:",
                "    connection: first",
                "    connection: second",
                "metadata:",
                "  team: data",
                "  team: analytics",
            ],
        ),
    )

    result = runner.invoke(app, ["pipeline", "validate", str(bad)])

    assert result.exit_code == 1
    assert "❌ Validation failed with status 422" in result.output
    assert "Error at: pipeline.pre-daily.connection" in result.output
    assert "Error at: metadata.team" in result.output
    assert "Duplicate key found in YAML: 'connection'" in result.output
    assert "Duplicate key found in YAML: 'team'" in result.output
    assert "YAML snippet:" in result.output
    assert "connection: first" in result.output
    assert "team: data" in result.output


def test_validate_oml_file_posts_expected_json(tmp_path, httpx_mock: HTTPXMock):
    pipeline_file = tmp_path / "pipeline.oml"
    pipeline_file.write_text('{"version": "v1", "name": "anomalies"}')
    httpx_mock.add_response(
        method="POST",
        url="https://app.getorchestra.io/api/engine/public/pipelines/schema",
        json={"ok": True},
        status_code=200,
    )

    result = runner.invoke(app, ["pipeline", "validate", str(pipeline_file)])

    assert result.exit_code == 0
    assert "Validation passed" in result.output
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"version": "v1", "name": "anomalies"}


def test_validate_oml_only_syntax_explains_limitation(tmp_path):
    pipeline_file = tmp_path / "pipeline.oml"
    pipeline_file.write_text("task:\n  sql: %sql select 1 %%\n")

    result = runner.invoke(app, ["pipeline", "validate", str(pipeline_file)])

    assert result.exit_code == 1
    assert "Invalid YAML" in result.output
    assert "embeds (`%sql ... %%`), those are not supported yet" in result.output


def test_validate_rejects_unsupported_extension(tmp_path):
    pipeline_file = tmp_path / "pipeline.json"
    pipeline_file.write_text('{"version": "v1"}')

    result = runner.invoke(app, ["pipeline", "validate", str(pipeline_file)])

    assert result.exit_code == 1
    assert "Unsupported file extension '.json'" in result.output
    assert ".yaml, .yml, .oml" in result.output
