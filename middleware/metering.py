import json
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
)

logger = logging.getLogger("stocktrends_api.metering")

ENABLE_AGENT_PAY = os.getenv("ENABLE_AGENT_PAY", "false").lower() == "true"
ENFORCE_AGENT_PAY = os.getenv("ENFORCE_AGENT_PAY", "false").lower() == "true"

AGENT_PAY_ENFORCE_PATH_PREFIXES = {"/v1/stim"}


class MeteringMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        request_id = str(uuid4())
        request.state.request_id = request_id

        path = request.url.path

        decision = classify_request(request)

        payment_required = decision.log_pricing_rule_id == "agent_pay_required"

        # --------------------------------------------------
        # 🚨 X402 ENFORCEMENT
        # --------------------------------------------------

        if ENABLE_AGENT_PAY and ENFORCE_AGENT_PAY and payment_required:

            # Check if payment signature exists
            payment_signature = has_payment_signature(request.headers)

            # --------------------------------------------------
            # NO PAYMENT → ISSUE 402 CHALLENGE
            # --------------------------------------------------
            if not payment_signature:

                challenge = build_x402_challenge(
                    amount=decision.price or 0.01,
                    path=path,
                    request_id=request_id,
                )

                # 🔑 CRITICAL: store ORIGINAL requirements
                request.state.x402_requirements = challenge["payment_required"]

                response = JSONResponse(
                    status_code=402,
                    content={
                        "error": "payment_required",
                        "request_id": request_id,
                    },
                )

                response.headers["PAYMENT-REQUIRED"] = json.dumps(
                    challenge["payment_required"]
                )
                response.headers["X-StockTrends-Payment-Required"] = "true"
                response.headers["X-StockTrends-Accepted-Payment-Methods"] = "x402"
                response.headers["X-StockTrends-Pricing-Rule"] = "agent_pay_required"

                return response

            # --------------------------------------------------
            # PAYMENT PRESENT → VERIFY
            # --------------------------------------------------

            try:

                payment_signature_raw = request.headers.get("payment-signature")

                if not payment_signature_raw:
                    return JSONResponse(
                        status_code=402,
                        content={
                            "error": "invalid_payment_signature",
                            "detail": "Missing PAYMENT-SIGNATURE header",
                            "request_id": request_id,
                        },
                    )

                # 🔑 CRITICAL: MUST reuse ORIGINAL requirements
                payment_requirements = request.state.x402_requirements

                if not payment_requirements:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": "server_error",
                            "detail": "Missing original payment requirements",
                            "request_id": request_id,
                        },
                    )

                logger.info(
                    "VERIFY BODY: %s",
                    json.dumps({
                        "paymentPayload": payment_signature_raw,
                        "paymentRequirements": payment_requirements
                    })
                )

                verification = verify_with_facilitator(
                    payment_signature=payment_signature_raw,
                    payment_requirements=payment_requirements,
                )

                if not verification.valid:
                    return JSONResponse(
                        status_code=402,
                        content={
                            "error": "payment_verification_failed",
                            "detail": verification.error_detail,
                            "request_id": request_id,
                        },
                    )

                settlement = settle_with_facilitator(
                    payment_signature=payment_signature_raw,
                    payment_requirements=payment_requirements,
                )

                if not settlement.valid:
                    return JSONResponse(
                        status_code=402,
                        content={
                            "error": "payment_settlement_failed",
                            "detail": settlement.error_detail,
                            "request_id": request_id,
                        },
                    )

                # --------------------------------------------------
                # PAYMENT SUCCESS → CONTINUE REQUEST
                # --------------------------------------------------

                response = await call_next(request)

                response.headers["X-Payment-Status"] = "settled"
                response.headers["X-StockTrends-Payment-Required"] = "false"

                return response

            except Exception as e:
                logger.error("x402 processing failed: %s", e, exc_info=True)

                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "payment_processing_error",
                        "detail": str(e),
                        "request_id": request_id,
                    },
                )

        # --------------------------------------------------
        # NORMAL FLOW (NO PAYMENT REQUIRED)
        # --------------------------------------------------

        response = await call_next(request)

        response.headers["X-StockTrends-Payment-Required"] = "false"

        return response