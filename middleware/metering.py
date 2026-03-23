import os
import time
import logging
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

logger = logging.getLogger("stocktrends_api.metering")

ENABLE_AGENT_PAY = os.getenv("ENABLE_AGENT_PAY", "false").lower() == "true"
ENFORCE_AGENT_PAY = os.getenv("ENFORCE_AGENT_PAY", "false").lower() == "true"
VALIDATE_AGENT_PAY_HEADERS = os.getenv("VALIDATE_AGENT_PAY_HEADERS", "false").lower() == "true"


def _parse_csv_env(env_name: str, default: str = "") -> set[str]:
    raw = os.getenv(env_name, default)
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


AGENT_PAY_ENFORCE_PATH_PREFIXES = _parse_csv_env(
    "AGENT_PAY_ENFORCE_PATH_PREFIXES",
    "/v1/stim",
)

AGENT_PAY_TEST_CUSTOMER_IDS = _parse_csv_env("AGENT_PAY_TEST_CUSTOMER_IDS")
AGENT_PAY_TEST_API_KEY_IDS = _parse_csv_env("AGENT_PAY_TEST_API_KEY_IDS")


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


def normalize_workflow_type(auth_mode: str | None, agent_id_header: str | None) -> str:
    if agent_id_header:
        return "agent"
    if auth_mode in ("api_key", "free_metered"):
        return "human"
    if auth_mode == "internal_automation":
        return "internal_automation"
    return "unknown"


def is_billable_request(decision) -> int:
    return 1 if decision.log_pricing_rule_id in {"default_subscription", "agent_pay_required"} else 0


def safe_decimal(value, default: str = "0"):
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def get_active_pricing_rule(rule_name: str | None) -> dict | None:
    if not rule_name:
        return None

    try:
        engine = get_metering_engine()
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                        id,
                        rule_name,
                        endpoint_pattern,
                        endpoint_family,
                        api_version,
                        access_type,
                        cost_per_request,
                        cost_unit,
                        free_tier_limit,
                        hard_limit,
                        requires_subscription,
                        requires_payment,
                        is_active
                    FROM api_pricing_rules
                    WHERE rule_name = :rule_name
                      AND is_active = 1
                    LIMIT 1
                    """
                ),
                {"rule_name": rule_name},
            ).mappings().first()

            return dict(row) if row else None

    except Exception as e:
        logger.error("Pricing rule lookup failed for %s: %s", rule_name, e, exc_info=True)
        return None


def resolve_economic_amounts(rule_name: str | None) -> tuple[Decimal, Decimal]:
    """
    Returns:
      unit_price_usd, billed_amount_usd

    Current model:
    - default_free -> 0, 0
    - default_free_metered -> 0, 0
    - default_subscription -> use rule unit price if present, but billed amount 0
      because subscription covers entitlement
    - agent_pay_required -> billed amount = unit price
    """
    rule = get_active_pricing_rule(rule_name)
    if not rule:
        return Decimal("0"), Decimal("0")

    unit_price_usd = safe_decimal(rule.get("cost_per_request"), "0")
    access_type = rule.get("access_type")

    if access_type == "paid":
        billed_amount_usd = unit_price_usd
    else:
        billed_amount_usd = Decimal("0")

    return unit_price_usd, billed_amount_usd


def build_econ_payment_fields(
    payment_required: int,
    payment_status: str,
    payment_method_header: str | None,
    payment_network_header: str | None,
    payment_token_header: str | None,
    payment_amount_header: str | None,
    payment_reference_header: str | None,
    decision,
) -> dict:
    """
    Prevent pollution of economics rows for non-required requests.
    """
    if not payment_required:
        return {
            "payment_status": "not_required",
            "payment_method": decision.econ_payment_method,
            "payment_network": None,
            "payment_token": None,
            "payment_amount_native": None,
            "payment_amount_usd": None,
            "payment_reference": None,
        }

    amount_native = None
    if payment_amount_header:
        try:
            amount_native = float(payment_amount_header)
        except (TypeError, ValueError):
            amount_native = None

    return {
        "payment_status": payment_status,
        "payment_method": payment_method_header or decision.econ_payment_method,
        "payment_network": payment_network_header,
        "payment_token": payment_token_header,
        "payment_amount_native": amount_native,
        "payment_amount_usd": None,
        "payment_reference": payment_reference_header,
    }


def _path_matches_enforcement_scope(path: str) -> bool:
    if not AGENT_PAY_ENFORCE_PATH_PREFIXES:
        return False
    return any(path.startswith(prefix) for prefix in AGENT_PAY_ENFORCE_PATH_PREFIXES)


def _caller_matches_test_allowlist(request: Request) -> bool:
    """
    If neither allowlist is configured, enforcement applies to everyone in scope.
    If one or both allowlists are configured, a match on either list enables enforcement.
    """
    customer_id = getattr(request.state, "customer_id", None)
    api_key_id = getattr(request.state, "api_key_id", None)

    has_customer_allowlist = bool(AGENT_PAY_TEST_CUSTOMER_IDS)
    has_api_key_allowlist = bool(AGENT_PAY_TEST_API_KEY_IDS)

    if not has_customer_allowlist and not has_api_key_allowlist:
        return True

    if has_customer_allowlist and customer_id and customer_id in AGENT_PAY_TEST_CUSTOMER_IDS:
        return True

    if has_api_key_allowlist and api_key_id and api_key_id in AGENT_PAY_TEST_API_KEY_IDS:
        return True

    return False


def should_enforce_agent_pay_for_request(request: Request, path: str, decision) -> bool:
    if not ENABLE_AGENT_PAY or not ENFORCE_AGENT_PAY:
        return False

    if decision.econ_payment_required != 1:
        return False

    if not _path_matches_enforcement_scope(path):
        return False

    if not _caller_matches_test_allowlist(request):
        return False

    return True


class MeteringMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        request_id = getattr(request.state, "request_id", None)
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

        auth_mode = getattr(request.state, "auth_mode", "unknown")
        has_paid_auth = auth_mode == "api_key"
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

        should_enforce_agent_pay = should_enforce_agent_pay_for_request(request, path, decision)

        validation_valid = True
        validation_error = None
        validation_detail = None

        if should_validate_agent_pay:
            validation_valid, validation_error, validation_detail = validate_payment_headers(request)

        economic_rule_name = decision.econ_pricing_rule_id or decision.log_pricing_rule_id
        unit_price_usd, billed_amount_usd = resolve_economic_amounts(economic_rule_name)

        if should_enforce_agent_pay and not validation_valid:
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
                "workflow_type": normalize_workflow_type(auth_mode, agent_id_header),
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
                logger.error("Metering request-log insert failed: %s", e, exc_info=True)

            if should_log_economics(decision):
                econ_payment_fields = build_econ_payment_fields(
                    payment_required=1,
                    payment_status="failed_validation",
                    payment_method_header=payment_method_header,
                    payment_network_header=payment_network_header,
                    payment_token_header=payment_token_header,
                    payment_amount_header=payment_amount_header,
                    payment_reference_header=payment_reference_header,
                    decision=decision,
                )

                econ = {
                    "request_id": request_id,
                    "customer_id": getattr(request.state, "customer_id", None),
                    "api_key_id": getattr(request.state, "api_key_id", None),
                    "pricing_rule_id": economic_rule_name,
                    "unit_price_usd": unit_price_usd,
                    "billed_amount_usd": billed_amount_usd,
                    "payment_required": 1,
                    **econ_payment_fields,
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
                    logger.error("Metering economics-log insert failed: %s", e, exc_info=True)

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
                "workflow_type": normalize_workflow_type(auth_mode, agent_id_header),
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
                "notes": str(caught_exception)[:255] if caught_exception else None,
            }

            try:
                log_api_request_event(event)
            except Exception as e:
                logger.error("Metering request-log insert failed: %s", e, exc_info=True)

            if should_log_economics(decision):
                payment_status = decision.econ_payment_status

                if decision.econ_payment_required and payment_method_header == "mpp":
                    if validation_valid:
                        payment_status = "presented"
                    else:
                        payment_status = "would_block_under_402" if not should_enforce_agent_pay else "failed_validation"

                econ_payment_fields = build_econ_payment_fields(
                    payment_required=decision.econ_payment_required,
                    payment_status=payment_status,
                    payment_method_header=payment_method_header,
                    payment_network_header=payment_network_header,
                    payment_token_header=payment_token_header,
                    payment_amount_header=payment_amount_header,
                    payment_reference_header=payment_reference_header,
                    decision=decision,
                )

                econ = {
                    "request_id": request_id,
                    "customer_id": getattr(request.state, "customer_id", None),
                    "api_key_id": getattr(request.state, "api_key_id", None),
                    "pricing_rule_id": economic_rule_name,
                    "unit_price_usd": unit_price_usd,
                    "billed_amount_usd": billed_amount_usd,
                    "payment_required": decision.econ_payment_required,
                    **econ_payment_fields,
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
                    logger.error("Metering economics-log insert failed: %s", e, exc_info=True)