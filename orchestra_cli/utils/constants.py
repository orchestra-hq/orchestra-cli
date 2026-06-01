import os

_PROD_BASE_URL = "https://app.getorchestra.io"


def get_api_url(path: str) -> str:
    suffix = f"/{path.lstrip('/')}" if path else ""
    return f"{get_base_url()}/api/engine/public{suffix}"


def get_base_url() -> str:
    return (os.getenv("BASE_URL") or _PROD_BASE_URL).strip().rstrip("/")


def get_create_pipeline_url() -> str:
    return get_api_url("pipelines")


def get_pipeline_url() -> str:
    return get_api_url("pipeline")


def get_pipeline_data_url() -> str:
    return get_api_url("pipeline/data")


def get_update_pipeline_url() -> str:
    return get_api_url("pipelines")


def get_delete_pipeline_url() -> str:
    return get_api_url("pipelines")


def get_pipeline_edit_url(pipeline_id: str) -> str:
    return f"{get_base_url()}/pipelines/{pipeline_id}/edit"
