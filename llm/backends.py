"""Model backends, chosen by LLM_BACKEND=meta_api|open_weights (spec/03).

A backend takes a Chat Completions request dict and returns the response as a
plain dict. Responses are parsed in llm.extract from message.content only.

open_weights is Muse Spark Open on Baseten Model APIs. Per Baseten's docs it
always reasons (reasoning arrives separately in message.reasoning_content and is
ignored) and it accepts json_schema without enforcing it. Following spec/03,
the schema is also in the prompt, llm.extract validates every response in code,
and invalid output gets exactly one repair attempt; a second invalid output is a
failure.
"""

from __future__ import annotations

import os

from llm.client import (
    OPEN_WEIGHTS_MODEL,
    STANDARD_MODEL,
    assert_standard_model,
    make_baseten_client,
    make_meta_client,
)
from llm.http_diagnostics import log_http_exception

BACKENDS = ("meta_api", "open_weights")


class BackendUnavailable(RuntimeError):
    pass


class MetaAPIBackend:
    name = "meta_api"
    model = STANDARD_MODEL
    enforces_schema = True

    def __init__(self, client=None):
        self._client = client  # created lazily so replay never needs a key

    def complete(self, request: dict) -> dict:
        assert_standard_model(request["model"])
        if self._client is None:
            self._client = make_meta_client()
        try:
            return self._client.chat.completions.create(**request).model_dump()
        except Exception as error:
            log_http_exception("meta_api /chat/completions", error, (getattr(self._client, "api_key", None),))
            raise


class OpenWeightsBackend:
    name = "open_weights"
    model = OPEN_WEIGHTS_MODEL
    enforces_schema = False  # Baseten: json_schema accepted, not enforced

    def __init__(self, client=None):
        self._client = client

    def complete(self, request: dict) -> dict:
        if request["model"] != OPEN_WEIGHTS_MODEL:
            raise ValueError(f"open_weights uses exactly {OPEN_WEIGHTS_MODEL}")
        if self._client is None:
            self._client = make_baseten_client()
        try:
            return self._client.chat.completions.create(**request).model_dump()
        except Exception as error:
            log_http_exception("open_weights /chat/completions", error, (getattr(self._client, "api_key", None),))
            raise


def get_backend(name: str | None = None):
    name = name or os.environ.get("LLM_BACKEND", "meta_api")
    if name == "meta_api":
        return MetaAPIBackend()
    if name == "open_weights":
        return OpenWeightsBackend()
    raise ValueError(f"LLM_BACKEND must be one of {BACKENDS}, not {name!r}")
