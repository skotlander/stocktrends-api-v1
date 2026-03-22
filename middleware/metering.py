import os
import time
import uuid
import logging
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request

from metering.logger import log_api_request_event, log_api_request_economics
from pricing.classifier import classify_request

logger = logging.getLogger("stocktrends_api.metering")

ENABLE_AGENT_PAY = os.getenv("ENABLE_AGENT_PAY", "false").lower() == "true"
ENFORCE_AGENT_PAY = os.getenv("ENFORCE_AGENT_PAY", "false").lower() == "true"
VALIDATE_AGENT_PAY_HEADERS = os.getenv("VALIDATE_AGENT_PAY_HEADERS", "false").lower() == "true"


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


def get_endpoint_family(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "v1":
        return parts[1]
    return None


def get_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else None


def get_response_size_bytes(response) -> int | None:
    if response is None:
        return None

    content_length = response.headers.get("content-length")
    if not content_length:
        return None

    try:
        return int(content_length)
    except (TypeError, ValueError):
        return None


def get_accepted_payment_methods(path: str, pricing_rule_id: str | None) -> str:
    if pricing_rule_id == "agent_pay_required":
        return "mpp,x402,crypto"

    if path.startswith("/v1/stim"):
        return "subscription,mpp,x402,crypto"

    if path.startswith("/v1/"):
        return "subscription"

    return "none"


def apply_pricing_headers(response, pricing_rule_id: str | None, payment_required: bool, accepted_methods: str):
    if pricing_rule_id:
        response.headers["X-StockTrends-Pricing-Rule"] = pricing_rule_id

    response.headers["X-StockTrends-Payment-Required"] = "true" if payment_required else "false"
    response.headers["X-StockTrends-Accepted-Payment-Methods"] = accepted_methods


def should_log_economics(decision) -> bool:
    return bool(decision.econ_pricing_rule_id)


def is_billable_request(decision) -> int:
    if decision.log_pricing_rule_id in {"default_subscription", "agent_pay_required"}:
        return 1
    return 0


class MeteringMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        request.state.request_id = request_id

        path = request.url.path
        method = request.method
        query_string = str(request.url.query)

        payment_method_header = request.headers.get("x-stocktrends-payment-method")
        payment_network_header = request.headers.get("x-stocktrends-payment-network")
        payment_token_header = request.headers.get("x-stocktrends-payment-token")
        payment_reference_header = request.headers.get("x-stocktrends-payment-reference")
        payment_amount_header = request.headers.get("x-stocktrends-payment-amount")

        agent_id_header = request.headers.get("x-stocktrends-agent-id")
        agent_type_header = request.headers.get("x-stocktrends-agent-type")
        agent_vendor_header = request.headers.get("x-stocktrends-agent-vendor")
        agent_version_header = request.headers.get("x-stocktrends-agent-version")
        request_purpose_header = request.headers.get("x-stocktrends-request-purpose")
        session_id_header = request.headers.get("x-stocktrends-session-id")

        has_paid_auth = getattr(request.state, "auth_mode", None) == "api_key"
        decision = classify_request(path=path, has_paid_auth=has_paid_auth)

        request.state.pricing_rule_id = decision.log_pricing_rule_id
        request.state.is_metered = decision.is_metered
        request.state.payment_required = decision.econ_payment_required
        request.state.payment_method_resolved = decision.econ_payment_method
        request.state.econ_pricing_rule_id = decision.econ_pricing_rule_id
        request.state.econ_payment_status = decision.econ_payment_status

        should_validate_agent_pay = (
            ENABLE_AGENT_PAY
            and VALIDATE_AGENT_PAY_HEADERS
            and decision.econ_payment_required == 1
            and payment_method_header == "mpp"
        )

        should_enforce_agent_pay = (
            ENABLE_AGENT_PAY
            and ENFORCE_AGENT_PAY
            and decision.econ_payment_required == 1
        )

        logger.warning(
            f"METERING DEBUG path={path} "
            f"request_id={request_id} "
            f"pricing_rule={decision.log_pricing_rule_id} "
            f"econ_pricing_rule={decision.econ_pricing_rule_id} "
            f"payment_required={decision.econ_payment_required} "
            f"ENFORCE_AGENT_PAY={ENFORCE_AGENT_PAY} "
            f"VALIDATE_AGENT_PAY_HEADERS={VALIDATE_AGENT_PAY_HEADERS} "
            f"should_validate_agent_pay={should_validate_agent_pay} "
            f"should_enforce_agent_pay={should_enforce_agent_pay} "
            f"payment_method_header={payment_method_header} "
            f"auth_mode={getattr(request.state, 'auth_mode', None)}"
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

            pricing_rule_for_headers = decision.econ_pricing_rule_id or decision.log_pricing_rule_id
            apply_pricing_headers(
                response,
                pricing_rule_id=pricing_rule_for_headers,
                payment_required=True,
                accepted_methods=get_accepted_payment_methods(path, pricing_rule_for_headers),
            )

            latency_ms = int((time.time() - start_time) * 1000)

            event = {
                "event_time_utc": datetime.now(timezone.utc),
                "request_id": request_id,
                "environment": "production",
                "api_key_id": getattr(request.state, "api_key_id", None),
                "customer_id": getattr(request.state, "customer_id", None),
                "subscription_id": getattr(request.state, "subscription_id", None),
                "plan_code": getattr(request.state, "plan_code", None),
                "actor_type": getattr(request.state, "actor_type", "unknown"),
                "workflow_type": "agent" if agent_id_header else "api",
                "agent_identifier": agent_id_header,
                "agent_id": agent_id_header,
                "endpoint_path": path,
                "route_template": None,
                "endpoint_family": get_endpoint_family(path),
                "http_method": method,
                "query_string": query_string,
                "symbol": request.query_params.get("symbol"),
                "exchange": request.query_params.get("exchange"),
                "symbol_exchange": request.query_params.get("symbol_exchange"),
                "status_code": 402,
                "success": 0,
                "latency_ms": latency_ms,
                "response_size_bytes": get_response_size_bytes(response),
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
                "referer": request.headers.get("referer"),
                "is_metered": decision.is_metered,
                "is_billable": is_billable_request(decision),
                "payment_method": payment_method_header or decision.log_payment_method,
                "pricing_rule_id": decision.log_pricing_rule_id,
                "error_code": validation_error,
                "notes": validation_detail,
            }

            try:
                log_api_request_event(event)
            except Exception as e:
                logger.error(f"Metering request-log insert failed: {e}")

            if should_log_economics(decision):
                econ = {
                    "request_id": request_id,
                    "pricing_rule_id": decision.econ_pricing_rule_id,
                    "unit_price_usd": 0,
                    "billed_amount_usd": 0,
                    "payment_required": 1,
                    "payment_status": "failed_validation",
                    "payment_method": payment_method_header or decision.econ_payment_method,
                    "payment_network": payment_network_header,
                    "payment_token": payment_token_header,
                    "payment_amount_native": payment_amount_header,
                    "payment_amount_usd": None,
                    "payment_reference": payment_reference_header,
                    "session_id": session_id_header,
                    "payment_channel_id": None,
                    "agent_id": agent_id_header,
                    "agent_type": agent_type_header,
                    "agent_vendor": agent_vendor_header,
                    "agent_version": agent_version_header,
                    "request_purpose": request_purpose_header,
                }

                try:
                    log_api_request_economics(econ)
                except Exception as e:
                    logger.error(f"Metering economics-log insert failed: {e}")

            return response

        response = None
        caught_exception = None

        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            caught_exception = exc
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            status_code = response.status_code if response is not None else 500
            success = 1 if status_code < 400 else 0

            pricing_rule_for_headers = decision.econ_pricing_rule_id or decision.log_pricing_rule_id
            payment_required_for_headers = bool(decision.econ_payment_required)
            accepted_methods = get_accepted_payment_methods(path, pricing_rule_for_headers)

            if response is not None:
                apply_pricing_headers(
                    response,
                    pricing_rule_id=pricing_rule_for_headers,
                    payment_required=payment_required_for_headers,
                    accepted_methods=accepted_methods,
                )

            event = {
                "event_time_utc": datetime.now(timezone.utc),
                "request_id": request_id,
                "environment": "production",
                "api_key_id": getattr(request.state, "api_key_id", None),
                "customer_id": getattr(request.state, "customer_id", None),
                "subscription_id": getattr(request.state, "subscription_id", None),
                "plan_code": getattr(request.state, "plan_code", None),
                "actor_type": getattr(request.state, "actor_type", "unknown"),
                "workflow_type": "agent" if agent_id_header else "api",
                "agent_identifier": agent_id_header,
                "agent_id": agent_id_header,
                "endpoint_path": path,
                "route_template": None,
                "endpoint_family": get_endpoint_family(path),
                "http_method": method,
                "query_string": query_string,
                "symbol": request.query_params.get("symbol"),
                "exchange": request.query_params.get("exchange"),
                "symbol_exchange": request.query_params.get("symbol_exchange"),
                "status_code": status_code,
                "success": success,
                "latency_ms": latency_ms,
                "response_size_bytes": get_response_size_bytes(response),
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
                "referer": request.headers.get("referer"),
                "is_metered": decision.is_metered,
                "is_billable": is_billable_request(decision),
                "payment_method": payment_method_header or decision.log_payment_method,
                "pricing_rule_id": decision.log_pricing_rule_id,
                "error_code": caught_exception.__class__.__name__ if caught_exception else None,
                "notes": str(caught_exception)[:500] if caught_exception else None,
            }

            try:
                log_api_request_event(event)
            except Exception as e:
                logger.error(f"Metering request-log insert failed: {e}")

            if should_log_economics(decision):
                payment_status = decision.econ_payment_status
                if decision.econ_payment_required and payment_method_header == "mpp":
                    payment_status = "presented"

                econ = {
                    "request_id": request_id,
                    "pricing_rule_id": decision.econ_pricing_rule_id,
                    "unit_price_usd": 0,
                    "billed_amount_usd": 0,
                    "payment_required": decision.econ_payment_required,
                    "payment_status": payment_status,
                    "payment_method": payment_method_header or decision.econ_payment_method,
                    "payment_network": payment_network_header,
                    "payment_token": payment_token_header,
                    "payment_amount_native": payment_amount_header,
                    "payment_amount_usd": None,
                    "payment_reference": payment_reference_header,
                    "session_id": session_id_header,
                    "payment_channel_id": None,
                    "agent_id": agent_id_header,
                    "agent_type": agent_type_header,
                    "agent_vendor": agent_vendor_header,
                    "agent_version": agent_version_header,
                    "request_purpose": request_purpose_header,
                }

                try:
                    log_api_request_economics(econ)
                except Exception as e:
                    logger.error(f"Metering economics-log insert failed: {e}")