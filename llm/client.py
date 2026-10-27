"""Meta Model API client (spec/03: Meta API facts).

OpenAI-SDK compatible. The key comes from MODEL_API_KEY and is passed to the
client explicitly; it is never logged, recorded or sent to the browser.
"""

from __future__ import annotations

import os

BASE_URL = "https://api.meta.ai/v1"
STANDARD_MODEL = "muse-spark-1.3"


def assert_standard_model(model: str) -> None:
    """Runtime calls use Standard IDs only; Contributor content may train Meta models."""
    if model.endswith("-contributor"):
        raise ValueError(f"{model} is a Contributor ID; the app uses Standard IDs only")


def make_meta_client():
    import openai

    try:
        key = os.environ["MODEL_API_KEY"]
    except KeyError:
        raise RuntimeError("MODEL_API_KEY is not set; use replay mode to run without a key") from None
    if not key.strip():
        raise RuntimeError("MODEL_API_KEY is empty; use replay mode to run without a key")
    return openai.OpenAI(base_url=BASE_URL, api_key=key, max_retries=0, timeout=60)
