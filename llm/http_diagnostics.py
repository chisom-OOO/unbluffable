"""HTTP status/request-ID diagnostics, excluding bodies, prompts and credentials."""

import json
import logging


LOG = logging.getLogger("uvicorn.error")


def redact_credentials(value, keys=()):
    text = str(value)
    for key in keys:
        if isinstance(key, str) and key:
            text = text.replace(key, "[REDACTED]")
    return text


def request_id(response, keys=()):
    value = response.headers.get("request-id") or response.headers.get("x-request-id")
    # JSON escaping prevents header values from adding spurious log lines.
    return json.dumps(redact_credentials(value, keys)[:512]) if value is not None else "none"


def log_http_failure(endpoint, response, keys=()):
    LOG.warning("model call %s failed: HTTP %s, request_id=%s",
                endpoint, response.status_code, request_id(response, keys))


def log_http_exception(endpoint, error, keys=()):
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and not 200 <= status < 300:
        log_http_failure(endpoint, response, keys)
