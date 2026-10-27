"""Model backends, chosen by LLM_BACKEND=meta_api|open_weights (spec/03).

A backend takes a Chat Completions request dict and returns the response as a
plain dict. `open_weights` (Muse Glimmer / Spark Open on a partner host) is a
stub until the Friday go/no-go.
"""

from __future__ import annotations

import os

from llm.client import assert_standard_model, make_meta_client

BACKENDS = ("meta_api", "open_weights")


class BackendUnavailable(RuntimeError):
    pass


class MetaAPIBackend:
    name = "meta_api"

    def __init__(self, client=None):
        self._client = client  # created lazily so replay never needs a key

    def complete(self, request: dict) -> dict:
        assert_standard_model(request["model"])
        if self._client is None:
            self._client = make_meta_client()
        return self._client.chat.completions.create(**request).model_dump()


class OpenWeightsBackend:
    name = "open_weights"

    def complete(self, request: dict) -> dict:
        raise BackendUnavailable(
            "open_weights backend is not implemented yet (spec/03: partner host, go/no-go Fri 30 Oct)"
        )


def get_backend(name: str | None = None):
    name = name or os.environ.get("LLM_BACKEND", "meta_api")
    if name == "meta_api":
        return MetaAPIBackend()
    if name == "open_weights":
        return OpenWeightsBackend()
    raise ValueError(f"LLM_BACKEND must be one of {BACKENDS}, not {name!r}")
