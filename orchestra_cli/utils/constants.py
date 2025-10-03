import os


def get_api_url(path: str):
    base_url = os.getenv("BASE_URL") or "https://app.getorchestra.io/api/engine/public/pipelines/{}"
    return base_url.format(path)
