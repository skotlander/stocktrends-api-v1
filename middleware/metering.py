import os
import time
import uuid
import logging
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request

from metering.logger import log_api_request_event

logger = logging.getLogger("stocktrends_api.metering")

ENABLE_AGENT_PAY = os.getenv("ENABLE_AGENT_PAY", "false").lower() == "true"
ENFORCE_AGENT_PAY = os.getenv("ENFORCE_AGENT_PAY", "false").lower() == "true"
VALIDATE_AGENT_PAY_HEADERS = os.getenv("VALIDATE_AGENT_PAY_HEADERS", "false").lower() == "true"


# -----------------------------
# Payment validation
# -----------------------------
def validate_payment_headers(request: Request):
    required_headers = [
        "x-stocktrends-payment-amount",
        "x-stocktrends-payment-network",
        "x-stocktrends-payment-reference",
    ]

    missing = [h for h in required_headers if h not in request.headers]

    if missing:
        return False, "missing_payment_headers", f"Missing required payment headers: {', '.join(missing)}"

    return True, None, None


# -----------------------------
# Pricing discovery headers
# -----------------------------
def apply_pricing_headers(response, pricing_rule_id: str, payment_required: bool, accepted_methods: str):
    response.headers["X-StockTrends-Pricing-Rule"] = pricing_rule_id
    response.headers["X-StockTrends-Payment-Required"] = "true" if payment_required else "false"
    response.headers["X-StockTrends-Accepted-Payment-Methods"] = accepted_methods


# -----------------------------
# Middleware
# -----------------------------
class MeteringMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # ✅ Always generate request_id
        request_id = str(uuid.uuid4())

        path = request.url.path
        method = request.method
        query_string = str(request.url.query)

        payment_method_header = request.headers.get("x-stocktrends-payment-method")

        should_validate_agent_pay = (
            ENABLE_AGENT_PAY and VALIDATE_AGENT_PAY_HEADERS and payment_method_header == "mpp"
        )

        should_enforce_agent_pay = (
            ENABLE_AGENT_PAY and ENFORCE_AGENT_PAY and path.startswith("/v1/")
        )

        logger.warning(
            f"METERING DEBUG path={path} "
            f"ENFORCE_AGENT_PAY={ENFORCE_AGENT_PAY} "
            f"VALIDATE_AGENT_PAY_HEADERS={VALIDATE_AGENT_PAY_HEADERS} "
            f"should_validate_agent_pay={should_validate_agent_pay} "
            f"payment_method_header={payment_method_header}"
        )

        validation_valid = True
        validation_error = None
        validation_detail = None

        if should_validate_agent_pay:
            validation_valid, validation_error, validation_detail = validate_payment_headers(request)

            logger.warning(
                f"METERING DEBUG validation valid={validation_valid} "
                f"error={validation_error} detail={validation_detail}"
            )

        # -----------------------------
        # 🚨 Enforcement branch (402)
        # -----------------------------
        if should_enforce_agent_pay and not validation_valid:

            logger.warning(f"METERING DEBUG returning 402 for path={path}")

            response = JSONResponse(
                status_code=402,
                content={
                    "error": validation_error,
                    "detail": validation_detail,
                    "request_id": request_id,
                },
            )

            # ✅ Pricing headers (ENFORCED)
            apply_pricing_headers(
                response,
                pricing_rule_id="agent_pay_required",
                payment_required=True,
                accepted_methods="mpp,x402,crypto",
            )

            latency_ms = int((time.time() - start_time) * 1000)

            event = {
                "event_time_utc": datetime.now(timezone.utc),
                "request_id": request_id,
                "environment": "production",
                "api_key_id": None,
                "customer_id": None,
                "subscription_id": None,
                "plan_code": None,
                "actor_type": "unknown",
                "workflow_type": "agent",
                "agent_identifier": None,
                "agent_id": None,
                "endpoint_path": path,
                "route_template": None,
                "endpoint_family": path.split("/")[2] if len(path.split("/")) > 2 else None,
                "http_method": method,
                "query_string": query_string,
                "symbol": request.query_params.get("symbol"),
                "exchange": request.query_params.get("exchange"),
                "symbol_exchange": request.query_params.get("symbol_exchange"),
                "status_code": 402,
                "success": 0,
                "latency_ms": latency_ms,
                "response_size_bytes": None,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "referer": request.headers.get("referer"),
                "is_metered": 1,
                "is_billable": 0,
                "payment_method": payment_method_header or "subscription",
                "pricing_rule_id": "agent_pay_required",
                "error_code": validation_error,
                "notes": validation_detail,
            }

            try:
                log_api_request_event(event)
            except Exception as e:
                logger.error(f"Metering request-log insert failed: {e}")

            return response  # ✅ ALWAYS RETURN

        # -----------------------------
        # ✅ Normal flow
        # -----------------------------
        response = await call_next(request)

        latency_ms = int((time.time() - start_time) * 1000)

        # ✅ Apply pricing headers (PASSIVE DISCOVERY MODE)
        if path.startswith("/v1/stim"):
            apply_pricing_headers(
                response,
                pricing_rule_id="default_subscription",
                payment_required=False,
                accepted_methods="subscription,mpp,x402,crypto",
            )

        event = {
            "event_time_utc": datetime.now(timezone.utc),
            "request_id": request_id,
            "environment": "production",
            "api_key_id": None,
            "customer_id": None,
            "subscription_id": None,
            "plan_code": None,
            "actor_type": "unknown",
            "workflow_type": "agent",
            "agent_identifier": None,
            "agent_id": None,
            "endpoint_path": path,
            "route_template": None,
            "endpoint_family": path.split("/")[2] if len(path.split("/")) > 2 else None,
            "http_method": method,
            "query_string": query_string,
            "symbol": request.query_params.get("symbol"),
            "exchange": request.query_params.get("exchange"),
            "symbol_exchange": request.query_params.get("symbol_exchange"),
            "status_code": response.status_code,
            "success": 1 if response.status_code < 400 else 0,
            "latency_ms": latency_ms,
            "response_size_bytes": None,
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "referer": request.headers.get("referer"),
            "is_metered": 1,
            "is_billable": 1,
            "payment_method": payment_method_header or "subscription",
            "pricing_rule_id": "default_subscription",
            "error_code": None,
            "notes": None,
        }

        try:
            log_api_request_event(event)
        except Exception as e:
            logger.error(f"Metering request-log insert failed: {e}")

        return response  # ✅ ALWAYS RETURN