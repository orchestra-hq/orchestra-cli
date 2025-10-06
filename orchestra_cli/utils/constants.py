import os

_PROD_BASE_URL = "https://app.getorchestra.io/api/engine/public/pipelines/{}"


def get_api_url(path: str) -> str:
    return (os.getenv("BASE_URL") or _PROD_BASE_URL).format(path)
