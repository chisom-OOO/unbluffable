"""Security headers on every HTTP response (decision log 42).

Only framing, sniffing and referrer rules: no full Content-Security-Policy, which could break
Pyodide (WASM from jsDelivr), CodeMirror (cdnjs), Firebase or Google Fonts.
"""

from __future__ import annotations

HEADERS = (
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
)
_NAMES = {name for name, _ in HEADERS}


class SecurityHeaders:
    """Pure ASGI middleware, so streamed responses and WebSockets pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in _NAMES]
                message = {**message, "headers": kept + list(HEADERS)}
            await send(message)

        await self.app(scope, receive, with_headers)
