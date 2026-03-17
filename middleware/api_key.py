import hashlib
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from db import get_auth_engine


ALLOWED_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def extract_api_key(request: Request) -> Optional[str]:
    # Primary: X-API-Key
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()

    # Fallback: Authorization Bearer
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

        # Public endpoints
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

        self.public_prefixes = [
            "/dataset/",
            "/.well-known/",
        ]

        # Free-tier endpoints (no key required, but metered)
        self.free_metered_paths = {
            "/v1/ai/context",
            "/v1/breadth/sector/latest",
        }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # --- Public routes ---
        if path in self.public_paths or any(path.startswith(p) for p in self.public_prefixes):
            return await call_next(request)

        # --- Free metered routes ---
        if path in self.free_metered_paths:
            return await call_next(request)

        # --- Protected routes ---
        if path.startswith("/v1/"):
            raw_key = extract_api_key(request)

            if not raw_key:
                return JSONResponse(
                    {"detail": "Missing API key"},
                    status_code=401,
                )

            key_hash = hash_api_key(raw_key)

            engine = get_auth_engine()

            with engine.connect() as conn:
                result = conn.execute(
                    """
                    SELECT 
                        k.id,
                        k.customer_id,
                        k.subscription_id,
                        k.status,
                        k.revoked_at,
                        s.status AS subscription_status,
                        p.code AS plan_code,
                        p.active AS plan_active
                    FROM api_keys k
                    LEFT JOIN api_subscriptions s ON k.subscription_id = s.id
                    LEFT JOIN api_plans p ON s.plan_id = p.id
                    WHERE k.key_hash = %s
                    LIMIT 1
                    """,
                    (key_hash,),
                ).fetchone()

                if not result:
                    return JSONResponse(
                        {"detail": "Invalid API key"},
                        status_code=401,
                    )

                (
                    key_id,
                    customer_id,
                    subscription_id,
                    key_status,
                    revoked_at,
                    subscription_status,
                    plan_code,
                    plan_active,
                ) = result

                # --- Key validation ---
                if key_status != "active" or revoked_at is not None:
                    return JSONResponse(
                        {"detail": "API key inactive"},
                        status_code=403,
                    )

                # --- Subscription validation ---
                if not subscription_id:
                    return JSONResponse(
                        {"detail": "No subscription linked to API key"},
                        status_code=403,
                    )

                if subscription_status not in ALLOWED_SUBSCRIPTION_STATUSES:
                    return JSONResponse(
                        {"detail": f"Subscription not active ({subscription_status})"},
                        status_code=403,
                    )

                # --- Plan validation ---
                if not plan_active:
                    return JSONResponse(
                        {"detail": "Plan is inactive"},
                        status_code=403,
                    )

                # --- OPTIONAL: Plan-based route restrictions ---
                if not self.is_plan_allowed(path, plan_code):
                    return JSONResponse(
                        {"detail": f"Plan '{plan_code}' does not allow this endpoint"},
                        status_code=403,
                    )

                # --- Update last_used_at ---
                conn.execute(
                    """
                    UPDATE api_keys
                    SET last_used_at = NOW()
                    WHERE id = %s
                    """,
                    (key_id,),
                )

            # Continue request
            response = await call_next(request)
            return response

        # Fallback
        return await call_next(request)



    def is_plan_allowed(self, path: str, plan_code: str) -> bool:
        sandbox_plus = {"sandbox", "research", "pro", "enterprise"}
        research_plus = {"research", "pro", "enterprise"}
        pro_plus = {"pro", "enterprise"}
        enterprise_only = {"enterprise"}

        # Research and above
        if path.startswith("/v1/stim"):
            return plan_code in research_plus

        # Pro and above
        if path.startswith("/v1/advanced") or path.startswith("/v1/batch"):
            return plan_code in pro_plus

        # Enterprise only
        if path.startswith("/v1/bulk"):
            return plan_code in enterprise_only

        # Default protected /v1 endpoints: any paid plan
        if path.startswith("/v1/"):
            return plan_code in sandbox_plus

        return True