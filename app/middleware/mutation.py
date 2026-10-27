"""Research-prototype ASGI middleware for bounded request translation.

This is a controlled lab prototype, not production security middleware.
It does not make client-visible route/schema transformations secret.
"""
import asyncio
import json
from typing import Any, Awaitable, Callable

ASGIApp = Callable[..., Awaitable[None]]
MAX_BODY_SIZE = 1 * 1024 * 1024
BODY_READ_TIMEOUT_SECONDS = 10.0


class SchemaMutationMiddleware:
    def __init__(self, app: ASGIApp, *, mode: str = "B", redis_client=None):
        self.app = app
        self.mode = mode.upper()
        self.redis = redis_client

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_mutated_route = path == "/api/mutated/epoch_x92"

        # Only transform the explicit research route. Unknown routes continue
        # to normal routing and will usually receive FastAPI's 404.
        if not is_mutated_route:
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except (TypeError, ValueError):
                await self._respond(send, 400, b"Invalid Content-Length")
                return
            if declared_length < 0:
                await self._respond(send, 400, b"Invalid Content-Length")
                return
            if declared_length > MAX_BODY_SIZE:
                await self._respond(send, 413, b"Payload Too Large")
                return

        body = bytearray()
        more_body = True
        while more_body:
            try:
                message = await asyncio.wait_for(
                    receive(), timeout=BODY_READ_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                await self._respond(send, 408, b"Request body read timeout")
                return

            msg_type = message.get("type")
            if msg_type == "http.disconnect":
                # The peer has gone away; do not call the application.
                return
            if msg_type != "http.request":
                # Be conservative about unexpected ASGI messages.
                await self._respond(send, 400, b"Unexpected ASGI request message")
                return

            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_SIZE:
                await self._respond(send, 413, b"Payload Too Large")
                return
            body.extend(chunk)
            more_body = bool(message.get("more_body", False))

        # Replay protection is only active in Configuration C. Redis must be
        # configured; failing closed avoids silently disabling the control.
        if self.mode == "C":
            nonce = headers.get(b"x-epoch-nonce")
            if not nonce or len(nonce) > 128:
                await self._respond(send, 400, b"Missing or invalid X-Epoch-Nonce")
                return
            redis_client = self.redis
            if redis_client is None:
                app = scope.get("app")
                state = getattr(app, "state", None)
                redis_client = getattr(state, "redis", None)
            if redis_client is None:
                await self._respond(send, 503, b"Replay protection unavailable")
                return
            try:
                accepted = await redis_client.set(
                    f"research:nonce:{nonce.decode('ascii', errors='strict')}",
                    "1",
                    ex=120,
                    nx=True,
                )
            except (UnicodeDecodeError, Exception):
                # Research prototype: fail closed if Redis is unavailable.
                await self._respond(send, 503, b"Replay protection unavailable")
                return
            if not accepted:
                await self._respond(send, 409, b"Replay detected")
                return

        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            await self._respond(send, 400, b"Invalid JSON")
            return
        if not isinstance(payload, dict):
            await self._respond(send, 400, b"JSON body must be an object")
            return

        # Deterministic mapping for the benchmark only. It is not a secret and
        # is not meant to represent cryptographic epoch-based mutation.
        if "x_829" not in payload or "q_01" not in payload:
            await self._respond(send, 400, b"Invalid mutated schema")
            return

        translated = {"item_id": payload["x_829"], "qty": payload["q_01"]}
        translated_body = json.dumps(translated, separators=(",", ":")).encode()

        scope = dict(scope)
        scope["path"] = "/api/v1/checkout"
        scope["raw_path"] = b"/api/v1/checkout"
        scope["headers"] = [
            (k, v) for k, v in scope.get("headers", [])
            if k.lower() not in (b"content-length", b"transfer-encoding")
        ] + [(b"content-length", str(len(translated_body)).encode("ascii"))]

        delivered = False

        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": translated_body,
                    "more_body": False,
                }
            # After the reconstructed body is delivered, continue forwarding
            # disconnect events from the original ASGI receive callable.
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _respond(send, status: int, body: bytes):
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})
