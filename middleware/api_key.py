import os
import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def _parse_keys(raw: str) -> set[str]:
    parts = [p.strip() for p in raw.replace("\n", ",").replace(" ", ",").split(",")]
    return {p for p in parts if p}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.keys = _parse_keys(os.getenv("API_KEYS", ""))

        self.public_paths = {
            "/",
            "/index.html",
            "/llms.txt",
            "/ai-dataset.json",
            "/tools.json",
            "/sitemap.xml",
            "/robots.txt",
            "/docs",
            "/openapi.json",
            "/health",
        }

        self.public_prefixes = (
            "/dataset/",
            "/.well-known/",
        )

        self.free_metered_paths = {
            "/v1/instruments/lookup",
            "/v1/ai/context",
        }

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id

        path = request.url.path
        request.state.auth_mode = "public"
        request.state.api_key_id = None

        is_public = (
            path in self.public_paths
            or any(path.startswith(prefix) for prefix in self.public_prefixes)
        )

        is_free_metered = path in self.free_metered_paths

        protected_v1 = path.startswith("/v1/") and not is_free_metered

        if protected_v1 and not is_public:
            supplied = request.headers.get("X-API-Key", "").strip()

            if not supplied:
                auth = request.headers.get("Authorization", "").strip()
                if auth.lower().startswith("bearer "):
                    supplied = auth[7:].strip()

            if not self.keys:
                return JSONResponse(
                    status_code=500,
                    content={"detail": "API keys not configured", "request_id": request_id},
                )

            if supplied not in self.keys:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )

            request.state.auth_mode = "api_key"
            request.state.api_key_id = supplied[:6] + "..." + supplied[-4:]

        elif is_free_metered:
            request.state.auth_mode = "free_metered"

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time-ms"] = str(int((time.time() - start) * 1000))
        return response