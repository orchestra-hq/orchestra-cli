import os

_PROD_BASE_URL = "https://app.getorchestra.io/api/engine/public/pipelines/{}"


def get_api_url(path: str) -> str:
    return (os.getenv("BASE_URL") or _PROD_BASE_URL).format(path)


def get_create_pipeline_url() -> str:
    return get_api_url("")


def get_update_pipeline_url(alias: str) -> str:
    return get_api_url(alias)
