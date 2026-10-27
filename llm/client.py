"""Model API clients (spec/03: Meta API facts; open-weights backend).

Both are OpenAI-SDK compatible. Each key comes from its own environment variable
and is passed to the client explicitly; keys stay on the server and are never
logged, recorded or sent to the browser.
"""

from __future__ import annotations

import os

BASE_URL = "https://api.meta.ai/v1"
STANDARD_MODEL = "muse-spark-1.3"

# Muse Spark Open on Baseten Model APIs (docs.baseten.co, checked 27 Oct 2026).
BASETEN_URL = "https://inference.baseten.co/v1"
OPEN_WEIGHTS_MODEL = "meta-models/muse-spark-open-1026"


class MissingKey(RuntimeError):
    pass


def assert_standard_model(model: str) -> None:
    """Runtime calls use Standard IDs only; Contributor content may train Meta models."""
    if model.endswith("-contributor"):
        raise ValueError(f"{model} is a Contributor ID; the app uses Standard IDs only")


def _key(name: str) -> str:
    try:
        key = os.environ[name]
    except KeyError:
        raise MissingKey(f"{name} is not set; use replay mode to run without a key") from None
    key = key.strip()  # pasted keys often carry a trailing newline, which is illegal in HTTP headers
    if not key:
        raise MissingKey(f"{name} is empty; use replay mode to run without a key")
    return key


def make_meta_client():
    import openai

    return openai.OpenAI(base_url=BASE_URL, api_key=_key("MODEL_API_KEY"), max_retries=0, timeout=60)


def make_baseten_client():
    import openai

    return openai.OpenAI(base_url=BASETEN_URL, api_key=_key("BASETEN_API_KEY"), max_retries=0, timeout=90)
