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

        with self.auth_engine.begin() as conn:
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

            if row and row["status"] == "active" and row["revoked_at"] is None:
                conn.execute(
                    text(
                        """
                        UPDATE api_keys
                        SET last_used_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                        """
                    ),
                    {"id": row["id"]},
                )

        return row

    def _write_request_log(
        self,
        request_id: str,
        api_key_id: str | None,
        customer_id: str | None,
        path: str,
        method: str,
        status_code: int,
        response_time_ms: int,
        auth_mode: str,
    ):
        with self.auth_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO api_request_logs
                    (
                        id,
                        request_id,
                        api_key_id,
                        customer_id,
                        path,
                        method,
                        status_code,
                        response_time_ms,
                        auth_mode
                    )
                    VALUES
                    (
                        :id,
                        :request_id,
                        :api_key_id,
                        :customer_id,
                        :path,
                        :method,
                        :status_code,
                        :response_time_ms,
                        :auth_mode
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "request_id": request_id,
                    "api_key_id": api_key_id,
                    "customer_id": customer_id,
                    "path": path,
                    "method": method,
                    "status_code": status_code,
                    "response_time_ms": response_time_ms,
                    "auth_mode": auth_mode,
                },
            )

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
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )
                response_time_ms = int((time.time() - start) * 1000)
                try:
                    self._write_request_log(
                        request_id=request_id,
                        api_key_id=None,
                        customer_id=None,
                        path=path,
                        method=request.method,
                        status_code=401,
                        response_time_ms=response_time_ms,
                        auth_mode="public",
                    )
                except Exception:
                    pass
                response.headers["X-Response-Time-ms"] = str(response_time_ms)
                return response

            try:
                row = self._lookup_api_key(supplied)
            except Exception as e:
                response = JSONResponse(
                    status_code=500,
                    content={
                        "detail": f"Auth database error: {str(e)}",
                        "request_id": request_id,
                    },
                    headers={"X-Request-Id": request_id},
                )
                response_time_ms = int((time.time() - start) * 1000)
                try:
                    self._write_request_log(
                        request_id=request_id,
                        api_key_id=None,
                        customer_id=None,
                        path=path,
                        method=request.method,
                        status_code=500,
                        response_time_ms=response_time_ms,
                        auth_mode="public",
                    )
                except Exception:
                    pass
                response.headers["X-Response-Time-ms"] = str(response_time_ms)
                return response

            if not row:
                response = JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid API key", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )
                response_time_ms = int((time.time() - start) * 1000)
                try:
                    self._write_request_log(
                        request_id=request_id,
                        api_key_id=None,
                        customer_id=None,
                        path=path,
                        method=request.method,
                        status_code=401,
                        response_time_ms=response_time_ms,
                        auth_mode="public",
                    )
                except Exception:
                    pass
                response.headers["X-Response-Time-ms"] = str(response_time_ms)
                return response

            if row["status"] != "active" or row["revoked_at"] is not None:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "API key inactive", "request_id": request_id},
                    headers={"X-Request-Id": request_id},
                )
                response_time_ms = int((time.time() - start) * 1000)
                try:
                    self._write_request_log(
                        request_id=request_id,
                        api_key_id=row["id"],
                        customer_id=row["customer_id"],
                        path=path,
                        method=request.method,
                        status_code=403,
                        response_time_ms=response_time_ms,
                        auth_mode="api_key",
                    )
                except Exception:
                    pass
                response.headers["X-Response-Time-ms"] = str(response_time_ms)
                return response

            request.state.auth_mode = "api_key"
            request.state.api_key_id = row["id"]
            request.state.customer_id = row["customer_id"]
            request.state.subscription_id = row["subscription_id"]

        elif is_free_metered:
            request.state.auth_mode = "free_metered"

        response = await call_next(request)
        response_time_ms = int((time.time() - start) * 1000)

        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time-ms"] = str(response_time_ms)

        try:
            self._write_request_log(
                request_id=request_id,
                api_key_id=request.state.api_key_id,
                customer_id=request.state.customer_id,
                path=path,
                method=request.method,
                status_code=response.status_code,
                response_time_ms=response_time_ms,
                auth_mode=request.state.auth_mode,
            )
        except Exception:
            pass

        return response