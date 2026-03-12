import hashlib
import time
import uuid

from fastapi import Request
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from db import get_auth_engine


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.auth_engine = get_auth_engine()

        self.public_paths = {
            "/",
            "/index.html",
            "/llms.txt",
            "/ai-dataset.json",
            "/tools.json",
            "/sitemap.xml",
            "/robots.txt",
            "/docs",
            "/v1/docs",
            "/openapi.json",
            "/v1/openapi.json",
            "/health",
        }

        self.public_prefixes = (
            "/dataset/",
            "/.well-known/",
        )

        self.free_metered_paths = {
            "/v1/ai/context",
            "/v1/breadth/sector/latest",
        }

    @staticmethod
    def _extract_supplied_key(request: Request) -> str:
        supplied = request.headers.get("X-API-Key", "").strip()

        if not supplied:
            auth = request.headers.get("Authorization", "").strip()
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()

        return supplied

    def _lookup_api_key(self, supplied: str):
        token_hash = hashlib.sha256(supplied.encode("utf-8")).hexdigest()

        with self.auth_engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                        id,
                        customer_id,
                        subscription_id,
                        key_prefix,
                        status,
                        revoked_at
                    FROM api_keys
                    WHERE key_hash = :key_hash
                    LIMIT 1
                    """
                ),
                {"key_hash": token_hash},
            ).mappings().first()

        return row

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

        request.state.request_id = request_id
        request.state.auth_mode = "public"
        request.state.api_key_id = None
        request.state.customer_id = None
        request.state.subscription_id = None

        path = request.url.path

        is_public = (
            path in self.public_paths
            or any(path.startswith(prefix) for prefix in self.public_prefixes)
        )

        is_free_metered = path in self.free_metered_paths
        protected_v1 = path.startswith("/v1/") and not is_free_metered

        if protected_v1 and not is_public:
            supplied = self._extract_supplied_key(request)

            if not supplied:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )

            try:
                row = self._lookup_api_key(supplied)
            except Exception as e:
                return JSONResponse(
                    status_code=500,
                    content={
                        "detail": f"Auth database error: {str(e)}",
                        "request_id": request_id,
                    },
                    headers={"X-Request-Id": request_id},
                )

            if not row:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid API key", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )

            if row["status"] != "active" or row["revoked_at"] is not None:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "API key inactive", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )

            request.state.auth_mode = "api_key"
            request.state.api_key_id = row["id"]
            request.state.customer_id = row["customer_id"]
            request.state.subscription_id = row["subscription_id"]

        elif is_free_metered:
            request.state.auth_mode = "free_metered"

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time-ms"] = str(int((time.time() - start) * 1000))
        return response