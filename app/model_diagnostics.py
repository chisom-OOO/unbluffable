"""One credential-safe model-list diagnostic per application startup."""

import json
import logging
import os

import httpx

from llm.client import BASE_URL
from llm.http_diagnostics import log_http_failure, redact_credentials


LOG = logging.getLogger("uvicorn.error")


async def log_startup_models(transport=None):
    try:
        key = os.environ["MODEL_API_KEY"].strip()
    except KeyError:
        return
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport) as client:
            response = await client.get(BASE_URL + "/models",
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    except httpx.RequestError as error:
        LOG.warning("model discovery /models HTTP unavailable model_ids=[] error=%s", type(error).__name__)
        return
    ids = []
    try:
        body = response.json()
        data = body.get("data", []) if isinstance(body, dict) else []
        if isinstance(data, list):
            ids = [redact_credentials(row["id"], (key,)) for row in data
                   if isinstance(row, dict) and isinstance(row.get("id"), str)]
    except ValueError:
        pass
    LOG.info("model discovery /models HTTP %s model_ids=%s", response.status_code, json.dumps(ids))
    if response.status_code != 200:
        log_http_failure("/models", response, (key,))
