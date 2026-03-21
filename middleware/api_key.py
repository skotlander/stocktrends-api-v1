import hashlib
from types import SimpleNamespace
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import text

from db import get_auth_engine


ALLOWED_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def extract_api_key(request: Request) -> Optional[str]:
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()

    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

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
            "/v1/pricing",
        }

        self.public_prefixes = [
            "/dataset/",
            "/.well-known/",
        ]

        self.free_metered_paths = {
            "/v1/ai/context",
            "/v1/breadth/sector/latest",
        }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Default request auth context
        request.state.auth_mode = "public"
        request.state.actor_type = "unknown"

        # Public routes
        if path in self.public_paths or any(path.startswith(prefix) for prefix in self.public_prefixes):
            return await call_next(request)

        # Free-metered routes
        if path in self.free_metered_paths:
            request.state.auth_mode = "free_metered"
            return await call_next(request)

        # Protected API routes
        if path.startswith("/v1/"):
            raw_key = extract_api_key(request)
            if not raw_key:
                return JSONResponse(
                    {"detail": "Missing API key"},
                    status_code=401,
                )

            key_hash = hash_api_key(raw_key)
            engine = get_auth_engine()

            with engine.begin() as conn:
                result = conn.execute(
                    text(
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
                        LEFT JOIN api_subscriptions s
                            ON k.subscription_id = s.id
                        LEFT JOIN api_plans p
                            ON s.plan_id = p.id
                        WHERE k.key_hash = :key_hash
                        LIMIT 1
                        """
                    ),
                    {"key_hash": key_hash},
                ).fetchone()

                if not result:
                    return JSONResponse(
                        {"detail": "Invalid API key"},
                        status_code=401,
                    )

                key_id = result[0]
                customer_id = result[1]
                subscription_id = result[2]
                key_status = result[3]
                revoked_at = result[4]
                subscription_status = result[5]
                plan_code = result[6]
                plan_active = result[7]

                if key_status != "active" or revoked_at is not None:
                    return JSONResponse(
                        {"detail": "API key inactive"},
                        status_code=403,
                    )

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

                if not plan_code:
                    return JSONResponse(
                        {"detail": "No plan linked to subscription"},
                        status_code=403,
                    )

                if not plan_active:
                    return JSONResponse(
                        {"detail": "Plan is inactive"},
                        status_code=403,
                    )

                if not self.is_plan_allowed(path, plan_code):
                    return JSONResponse(
                        {"detail": f"Plan '{plan_code}' does not allow this endpoint"},
                        status_code=403,
                    )

                conn.execute(
                    text(
                        """
                        UPDATE api_keys
                        SET last_used_at = NOW()
                        WHERE id = :key_id
                        """
                    ),
                    {"key_id": key_id},
                )

                request.state.api_key_id = key_id
                request.state.customer_id = customer_id
                request.state.subscription_id = subscription_id
                request.state.plan_code = plan_code
                request.state.auth_mode = "api_key"
                request.state.actor_type = "external_customer"
                request.state.auth_context = SimpleNamespace(
                    api_key_id=key_id,
                    customer_id=customer_id,
                    subscription_id=subscription_id,
                    plan_code=plan_code,
                    actor_type="external_customer",
                )

            return await call_next(request)

        return await call_next(request)

    def is_plan_allowed(self, path: str, plan_code: str) -> bool:
        sandbox_plus = {"sandbox", "research", "pro", "enterprise"}
        research_plus = {"research", "pro", "enterprise"}

        if path.startswith("/v1/stim"):
            return plan_code in research_plus

        if path.startswith("/v1/"):
            return plan_code in sandbox_plus

        return True