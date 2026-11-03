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

import httpx

from app import limits
from llm.client import (
    BASE_URL,
    BASETEN_URL,
    _key,
    OPEN_WEIGHTS_MODEL,
    STANDARD_MODEL,
    assert_standard_model,
    make_baseten_client,
    make_meta_client,
)
from llm.http_diagnostics import log_http_exception, log_http_failure

BACKENDS = ("meta_api", "open_weights")


class BackendUnavailable(RuntimeError):
    pass


class BackendResponseError(BackendUnavailable):
    """A failed HTTP response; its body is never part of the exception text."""

    def __init__(self, response):
        super().__init__("The model request failed.")
        self.response = response


async def _acomplete(backend, request, transport=None):
    """Native async transport so cancelled voice checks stop their HTTP request."""
    key = _key(backend.key_variable)
    async with httpx.AsyncClient(timeout=90, follow_redirects=False, transport=transport) as client:
        response = await client.post(backend.base_url + "/chat/completions", json=request,
            headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        body = response.json()
    except ValueError:
        log_http_failure(backend.name + " /chat/completions", response, (key,))
        raise BackendResponseError(response) from None
    if response.status_code != 200 or not isinstance(body, dict) or body.get("error") or body.get("type") == "error":
        log_http_failure(backend.name + " /chat/completions", response, (key,))
        raise BackendResponseError(response)
    spent(request, body)
    return body


def spent(request: dict, body) -> None:
    """Decision log 42: every live call adds its estimated cost to the daily meter."""
    limits.GUARD.add_tokens(request.get("model"), body.get("usage") if isinstance(body, dict) else None)


class MetaAPIBackend:
    name = "meta_api"
    model = STANDARD_MODEL
    base_url = BASE_URL
    key_variable = "MODEL_API_KEY"
    enforces_schema = True

    def __init__(self, client=None):
        self._client = client  # created lazily so replay never needs a key

    def complete(self, request: dict) -> dict:
        assert_standard_model(request["model"])
        if self._client is None:
            self._client = make_meta_client()
        try:
            body = self._client.chat.completions.create(**request).model_dump()
        except Exception as error:
            log_http_exception("meta_api /chat/completions", error, (getattr(self._client, "api_key", None),))
            raise
        spent(request, body)
        return body

    async def acomplete(self, request: dict, *, transport=None) -> dict:
        assert_standard_model(request["model"])
        if request["model"] != self.model:
            raise ValueError(f"meta_api uses exactly {self.model}")
        return await _acomplete(self, request, transport)


class OpenWeightsBackend:
    name = "open_weights"
    model = OPEN_WEIGHTS_MODEL
    base_url = BASETEN_URL
    key_variable = "BASETEN_API_KEY"
    enforces_schema = False  # Baseten: json_schema accepted, not enforced

    def __init__(self, client=None):
        self._client = client

    def complete(self, request: dict) -> dict:
        if request["model"] != OPEN_WEIGHTS_MODEL:
            raise ValueError(f"open_weights uses exactly {OPEN_WEIGHTS_MODEL}")
        if self._client is None:
            self._client = make_baseten_client()
        try:
            body = self._client.chat.completions.create(**request).model_dump()
        except Exception as error:
            log_http_exception("open_weights /chat/completions", error, (getattr(self._client, "api_key", None),))
            raise
        spent(request, body)
        return body

    async def acomplete(self, request: dict, *, transport=None) -> dict:
        if request["model"] != self.model:
            raise ValueError(f"open_weights uses exactly {self.model}")
        return await _acomplete(self, request, transport)


def get_backend(name: str | None = None):
    name = name or os.environ.get("LLM_BACKEND", "meta_api")
    if name == "meta_api":
        return MetaAPIBackend()
    if name == "open_weights":
        return OpenWeightsBackend()
    raise ValueError(f"LLM_BACKEND must be one of {BACKENDS}, not {name!r}")
