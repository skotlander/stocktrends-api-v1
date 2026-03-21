import os
import time
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from metering.logger import log_api_request_event, log_api_request_economics
from pricing.classifier import classify_request


logger = logging.getLogger("stocktrends_api.metering")


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


def parse_decimal_or_none(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


class MeteringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()

        path = request.url.path
        method = request.method
        query_string = request.url.query or None

        user_agent = request.headers.get("user-agent")
        referer = request.headers.get("referer")

        # Agent headers
        agent_identifier = request.headers.get("x-stocktrends-agent-id")
        agent_id = agent_identifier
        agent_type_header = request.headers.get("x-stocktrends-agent-type")
        agent_vendor = request.headers.get("x-stocktrends-agent-vendor")
        agent_version = request.headers.get("x-stocktrends-agent-version")
        request_purpose = request.headers.get("x-stocktrends-request-purpose")
        session_id = request.headers.get("x-stocktrends-session-id")

        # Future payment headers (passive capture only)
        payment_method_header = request.headers.get("x-stocktrends-payment-method")
        payment_network_header = request.headers.get("x-stocktrends-payment-network")
        payment_token_header = request.headers.get("x-stocktrends-payment-token")
        payment_reference_header = request.headers.get("x-stocktrends-payment-reference")
        payment_amount_header = request.headers.get("x-stocktrends-payment-amount")
        pricing_rule_header = request.headers.get("x-stocktrends-pricing-rule")

        payment_amount_native = parse_decimal_or_none(payment_amount_header)

        x_forwarded_for = request.headers.get("x-forwarded-for")
        client_ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else (
            request.client.host if request.client else None
        )

        symbol, exchange, symbol_exchange = extract_symbol_info(request)
        endpoint_family = infer_endpoint_family(path)

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

            request_id = getattr(request.state, "request_id", None)

            auth_ctx = getattr(request.state, "auth_context", None)
            api_key_id = getattr(auth_ctx, "api_key_id", getattr(request.state, "api_key_id", None))
            customer_id = getattr(auth_ctx, "customer_id", getattr(request.state, "customer_id", None))
            subscription_id = getattr(auth_ctx, "subscription_id", getattr(request.state, "subscription_id", None))
            plan_code = getattr(auth_ctx, "plan_code", getattr(request.state, "plan_code", None))
            actor_type = getattr(auth_ctx, "actor_type", getattr(request.state, "actor_type", "unknown"))

            workflow_type = infer_workflow_type(user_agent, agent_identifier, actor_type)

            has_paid_auth = bool(api_key_id or customer_id)
            decision = classify_request(path, has_paid_auth)

            # Raw request log keeps the existing classification behavior.
            # Optional client-declared pricing rule is NOT trusted to override the system rule yet.
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
                "agent_id": agent_id,
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
                "is_metered": decision.is_metered,
                "is_billable": 0,
                "payment_method": decision.log_payment_method,
                "pricing_rule_id": decision.log_pricing_rule_id,
                "error_code": error_code,
                "notes": None,
            }

            try:
                log_api_request_event(event)
            except Exception as exc:
                logger.exception("Metering request-log insert failed: %s", exc)
                return

            if decision.is_metered and request_id and decision.econ_pricing_rule_id:
                econ = {
                    "request_id": request_id,
                    "pricing_rule_id": pricing_rule_header or decision.econ_pricing_rule_id,
                    "unit_price_usd": None,
                    "billed_amount_usd": None,
                    "payment_required": decision.econ_payment_required,
                    "payment_status": decision.econ_payment_status,
                    "payment_method": payment_method_header or decision.econ_payment_method,
                    "payment_network": payment_network_header,
                    "payment_token": payment_token_header,
                    "payment_amount_native": payment_amount_native,
                    "payment_amount_usd": None,
                    "payment_reference": payment_reference_header,
                    "session_id": session_id,
                    "payment_channel_id": None,
                    "agent_id": agent_id,
                    "agent_type": agent_type_header or ("agent" if agent_id else None),
                    "agent_vendor": agent_vendor,
                    "agent_version": agent_version,
                    "request_purpose": request_purpose,
                }

                try:
                    log_api_request_economics(econ)
                except Exception as exc:
                    logger.exception("Metering economics insert failed: %s", exc)