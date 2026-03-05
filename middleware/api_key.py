import os
import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def _parse_keys(raw: str) -> set[str]:
    # supports comma-separated or whitespace-separated lists
    parts = [p.strip() for p in raw.replace("\n", ",").replace(" ", ",").split(",")]
    return {p for p in parts if p}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """
    Protects /v1/* routes with an API key.
    Allows discovery endpoints (/, /dataset/, /llms.txt, etc) without auth.

    Looks for:
      - header: X-API-Key
      - header: Authorization: Bearer <key>
    """

    def __init__(self, app, protected_prefix: str = "/v1"):
        super().__init__(app)
        self.protected_prefix = protected_prefix
        self.keys = _parse_keys(os.getenv("API_KEYS", ""))

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id

        path = request.url.path

        # Only protect /v1/*
        if path.startswith(self.protected_prefix):
            if not self.keys:
                # Fail closed if you forgot to configure keys
                return JSONResponse(
                    status_code=500,
                    content={"detail": "API keys not configured", "request_id": request_id},
                )

            supplied = request.headers.get("X-API-Key", "").strip()

            # Support Authorization: Bearer <key>
            if not supplied:
                auth = request.headers.get("Authorization", "").strip()
                if auth.lower().startswith("bearer "):
                    supplied = auth[7:].strip()

            if supplied not in self.keys:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )

            # optionally expose key id in logs (not the full key)
            request.state.api_key_id = supplied[:6] + "..." + supplied[-4:]

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time-ms"] = str(int((time.time() - start) * 1000))
        return response
