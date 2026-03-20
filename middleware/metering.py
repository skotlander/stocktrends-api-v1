import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from metering.logger import log_api_request_event


logger = logging.getLogger("stocktrends_api.metering")


NON_METERED_PATHS = {
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

FREE_METERED_PATHS = {
    "/v1/ai/context",
    "/v1/breadth/sector/latest",
}


ENDPOINT_FAMILY_PREFIXES = {
    "/v1/ai": "ai",
    "/v1/instruments": "instruments",
    "/v1/prices": "prices",
    "/v1/indicators": "indicators",
    "/v1/selections": "selections",
    "/v1/stim": "stim",
    "/v1/selections-published": "selections_published",
    "/v1/stwr": "stwr",
    "/v1/meta": "meta",
    "/v1/breadth": "breadth",
    "/v1/leadership": "leadership",
}


def infer_endpoint_family(path: str) -> Optional[str]:
    for prefix, family in ENDPOINT_FAMILY_PREFIXES.items():
        if path.startswith(prefix):
            return family
    return None


def infer_workflow_type(user_agent: str | None, agent_identifier: str | None, actor_type: str) -> str:
    if actor_type == "internal_service":
        return "internal_automation"

    if agent_identifier:
        return "agent"

    if not user_agent:
        return "unknown"

    ua = user_agent.lower()

    if any(token in ua for token in ["python", "curl", "httpx", "postman", "insomnia", "bot", "agent"]):
        return "agent"

    if any(token in ua for token in ["mozilla", "chrome", "safari", "firefox", "edge"]):
        return "human"

    return "unknown"


def extract_symbol_info(request: Request) -> tuple[Optional[str], Optional[str], Optional[str]]:
    qp = request.query_params
    symbol = qp.get("symbol")
    exchange = qp.get("exchange")

    symbol_exchange = None
    if symbol and exchange:
        symbol_exchange = f"{symbol}:{exchange}"

    return symbol, exchange, symbol_exchange


class MeteringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()

        path = request.url.path
        method = request.method
        query_string = request.url.query or None
        request_id = getattr(request.state, "request_id", None)

        user_agent = request.headers.get("user-agent")
        referer = request.headers.get("referer")
        agent_identifier = request.headers.get("x-stocktrends-agent-id")

        x_forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else (
            request.client.host if request.client else None
        )

        auth_ctx = getattr(request.state, "auth_context", None)

        api_key_id = getattr(auth_ctx, "api_key_id", None)
        customer_id = getattr(auth_ctx, "customer_id", None)
        subscription_id = getattr(auth_ctx, "subscription_id", None)
        plan_code = getattr(auth_ctx, "plan_code", None)
        actor_type = getattr(auth_ctx, "actor_type", getattr(request.state, "actor_type", "unknown"))

        workflow_type = infer_workflow_type(user_agent, agent_identifier, actor_type)
        endpoint_family = infer_endpoint_family(path)

        symbol, exchange, symbol_exchange = extract_symbol_info(request)

        is_metered = 0
        if path in FREE_METERED_PATHS:
            is_metered = 1
        elif path not in NON_METERED_PATHS and path.startswith("/v1/") and (api_key_id or customer_id):
            is_metered = 1

        is_billable = 0

        status_code = 500
        response_size_bytes = None
        error_code = None

        try:
            response = await call_next(request)
            status_code = response.status_code

            content_length = response.headers.get("content-length")
            if content_length and content_length.isdigit():
                response_size_bytes = int(content_length)

            return response

        except Exception as exc:
            error_code = exc.__class__.__name__
            raise

        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            success = 1 if 200 <= status_code < 400 else 0

            event = {
                "event_time_utc": datetime.now(timezone.utc),
                "request_id": request_id,
                "environment": os.getenv("API_ENV", "production"),
                "api_key_id": api_key_id,
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "plan_code": plan_code,
                "actor_type": actor_type,
                "workflow_type": workflow_type,
                "agent_identifier": agent_identifier,
                "endpoint_path": path,
                "route_template": None,
                "endpoint_family": endpoint_family,
                "http_method": method,
                "query_string": query_string,
                "symbol": symbol,
                "exchange": exchange,
                "symbol_exchange": symbol_exchange,
                "status_code": status_code,
                "success": success,
                "latency_ms": latency_ms,
                "response_size_bytes": response_size_bytes,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "referer": referer,
                "is_metered": is_metered,
                "is_billable": is_billable,
                "error_code": error_code,
                "notes": None,
            }

            try:
                log_api_request_event(event)
            except Exception as exc:
                logger.exception("Metering insert failed: %s", exc)