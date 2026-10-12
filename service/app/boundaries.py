"""Bound request bytes before JSON parsing and retain privacy through response send."""

from __future__ import annotations

import asyncio
import logging
import time

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .redaction import _VISITOR_KEY

MAX_BODY_BYTES = 1048576
BODY_READ_SECONDS = 15


class RequestBoundaries:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        keys = [
            value.decode("latin-1").strip()
            for name, value in headers
            if name.lower() == b"x-roadmodel-visitor-key"
        ]
        token = _VISITOR_KEY.set(keys[0] if keys else None)
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        async def error(status: int, code: str) -> None:
            await JSONResponse({"error": code}, status_code=status)(scope, receive, tracked_send)

        try:
            if len(keys) > 1 or (keys and len(keys[0]) > 8192):
                await error(400, "invalid_request")
                return
            lengths = [value for name, value in headers if name.lower() == b"content-length"]
            encodings = [value for name, value in headers if name.lower() == b"content-encoding"]
            if any(value.lower() != b"identity" for value in encodings):
                await error(415, "unsupported_encoding")
                return
            if len(lengths) > 1 or (lengths and (len(lengths[0]) > 10 or not lengths[0].isdigit())):
                await error(400, "invalid_request")
                return
            declared = int(lengths[0]) if lengths else None
            if declared is not None and declared > MAX_BODY_BYTES:
                await error(413, "request_too_large")
                return
            body = bytearray()
            body_deadline = time.monotonic() + BODY_READ_SECONDS
            empty_chunks = 0
            try:
                async with asyncio.timeout(BODY_READ_SECONDS):
                    while True:
                        if time.monotonic() >= body_deadline:
                            raise TimeoutError
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        empty_chunks = empty_chunks + 1 if not chunk else 0
                        if empty_chunks > 128:
                            await error(400, "invalid_request")
                            return
                        if len(body) + len(chunk) > MAX_BODY_BYTES:
                            await error(413, "request_too_large")
                            return
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await error(408, "request_timeout")
                return
            if declared is not None and declared != len(body):
                await error(400, "invalid_request")
                return
            delivered = False

            async def replay() -> Message:
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, replay, tracked_send)
        except Exception:
            # No raw exception may escape to an ASGI server after the key scope
            # resets. The body is fixed even for response-validation failures.
            logging.getLogger(__name__).warning("request failed unexpectedly")
            if not started:
                try:
                    await error(502, "provider_error")
                except Exception:
                    # A disconnected response transport must not rethrow a
                    # chained provider exception after the privacy scope ends.
                    logging.getLogger(__name__).warning("error response unavailable")
        finally:
            _VISITOR_KEY.reset(token)
