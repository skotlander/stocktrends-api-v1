import os
import re
import time
import logging
from uuid import uuid4
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request

from metering.logger import (
    log_api_request_event,
    log_api_request_economics,
    get_metering_engine,
)
from pricing.classifier import classify_request
from payments.x402 import (
    is_x402_payment_method,
    build_x402_challenge,
    validate_x402_payment,
    verify_with_facilitator,
    settle_with_facilitator,
    has_payment_signature,
    build_x402_requirements,
)

logger = logging.getLogger("stocktrends_api.metering")

ENABLE_AGENT_PAY = os.getenv("ENABLE_AGENT_PAY", "false").lower() == "true"
ENFORCE_AGENT_PAY = os.getenv("ENFORCE_AGENT_PAY", "false").lower() == "true"

MAX_AGENT_IDENTIFIER_LENGTH = 255
_AGENT_IDENTIFIER_ALLOWED_RE = re.compile(r"[^a-zA-Z0-9._:@/\-]+")


# =========================
# Replay Protection
# =========================
def is_payment_reference_used(ref: str) -> bool:
    try:
        engine = get_metering_engine()
        with engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT 1 FROM api_request_economics
                    WHERE payment_reference = :ref
                    LIMIT 1
                """),
                {"ref": ref},
            ).first()
            return row is not None
    except Exception as e:
        logger.error("Replay check failed: %s", e)
        return False


# =========================
# Utility
# =========================
def normalize_agent_identifier(agent_id_header: str | None) -> str | None:
    if not agent_id_header:
        return None
    normalized = agent_id_header.lower()
    normalized = _AGENT_IDENTIFIER_ALLOWED_RE.sub("-", normalized)
    return normalized.strip("-")[:MAX_AGENT_IDENTIFIER_LENGTH]


def apply_pricing_headers(response, pricing_rule_id, payment_required, accepted_methods):
    if pricing_rule_id:
        response.headers["X-StockTrends-Pricing-Rule"] = pricing_rule_id
    response.headers["X-StockTrends-Payment-Required"] = "true" if payment_required else "false"
    response.headers["X-StockTrends-Accepted-Payment-Methods"] = accepted_methods


# =========================
# Middleware
# =========================
class MeteringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        request_id = getattr(request.state, "request_id", None)
        path = request.url.path
        method = request.method

        payment_method_header = request.headers.get("x-stocktrends-payment-method")
        normalized_payment_method = (payment_method_header or "").lower()

        agent_identifier = normalize_agent_identifier(
            request.headers.get("x-stocktrends-agent-id")
        )

        decision = classify_request(
            path=path,
            has_paid_auth=False,
            payment_method_header=payment_method_header,
            plan_code=None,
            agent_identifier=agent_identifier,
        )

        unit_price_usd = Decimal("0.0025")

        # =========================
        # ENFORCE X402
        # =========================
        if ENABLE_AGENT_PAY and ENFORCE_AGENT_PAY:
            if is_x402_payment_method(normalized_payment_method):

                # ---- STEP 1: No signature → challenge
                if not has_payment_signature(request.headers):
                    body, payment_required_header = build_x402_challenge(
                        path=path,
                        amount_usd=unit_price_usd,
                    )

                    response = JSONResponse(status_code=402, content=body)
                    response.headers["PAYMENT-REQUIRED"] = payment_required_header

                    apply_pricing_headers(
                        response,
                        "agent_pay_required",
                        True,
                        "x402",
                    )

                    return response

                # ---- STEP 2: Validate signature format
                x402_result = validate_x402_payment(
                    request.headers,
                    required_amount_usd=unit_price_usd,
                )

                if not x402_result.valid:
                    return JSONResponse(
                        status_code=402,
                        content={
                            "error": "invalid_payment_signature",
                            "detail": x402_result.error_detail,
                        },
                    )

                signature = x402_result.payment_signature

                # ---- STEP 3: Replay protection
                if is_payment_reference_used(signature):
                    return JSONResponse(
                        status_code=409,
                        content={
                            "error": "duplicate_payment",
                            "detail": "Payment already used",
                        },
                    )

                # ---- STEP 4: Build requirements
                payment_requirements = build_x402_requirements(
                    path=path,
                    amount_usd=unit_price_usd,
                )

                # ---- STEP 5: VERIFY
                verify_result = verify_with_facilitator(
                    payment_signature=signature,
                    payment_requirements=payment_requirements,
                )

                if not verify_result.valid:
                    return JSONResponse(
                        status_code=402,
                        content={
                            "error": "payment_verification_failed",
                            "detail": verify_result.error_detail,
                        },
                    )

                # ---- STEP 6: SETTLE
                settle_result = settle_with_facilitator(
                    payment_signature=signature,
                    payment_requirements=payment_requirements,
                )

                if not settle_result.valid:
                    return JSONResponse(
                        status_code=402,
                        content={
                            "error": "payment_settlement_failed",
                            "detail": settle_result.error_detail,
                        },
                    )

                payment_status = "settled"

            else:
                payment_status = "not_required"

        else:
            payment_status = "not_required"

        # =========================
        # Execute Request
        # =========================
        response = await call_next(request)

        latency_ms = int((time.time() - start_time) * 1000)

        # =========================
        # Logging
        # =========================
        try:
            log_api_request_event({
                "request_id": request_id,
                "endpoint_path": path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "agent_identifier": agent_identifier,
            })
        except Exception as e:
            logger.error("Event log failed: %s", e)

        try:
            log_api_request_economics({
                "request_id": request_id,
                "pricing_rule_id": "agent_pay_required",
                "payment_method": "x402",
                "payment_status": payment_status,
                "payment_reference": request.headers.get("payment-signature"),
                "agent_id": agent_identifier,
                "payment_amount_usd": float(unit_price_usd),
            })
        except Exception as e:
            logger.error("Econ log failed: %s", e)

        return response