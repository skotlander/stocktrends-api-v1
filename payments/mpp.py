from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Callable, Optional


MPP_PAYMENT_CHANNEL_ID_HEADERS = (
    "x-stocktrends-payment-channel-id",
    "x-payment-channel-id",
)

MPP_REQUIRED_HEADERS = (
    "x-stocktrends-payment-method",
    "x-stocktrends-payment-network",
    "x-stocktrends-payment-reference",
    "x-stocktrends-payment-amount",
)


def _normalize_header(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _extract_payment_channel_id(headers) -> str | None:
    for header_name in MPP_PAYMENT_CHANNEL_ID_HEADERS:
        value = _normalize_header(headers.get(header_name))
        if value:
            return value
    return None


def enforce_mpp_payment(
    *,
    headers,
    validation_valid: bool,
    validation_error: str | None,
    validation_detail: str | None,
    amount_usd: Optional[Decimal] = None,
    replay_checker: Optional[Callable[[str], bool]] = None,
    path: str = "",
    pricing_rule_id: Optional[str] = None,
    request_id: Optional[str] = None,
    **_kwargs,
):
    """
    MPP payment enforcement — control-plane-backed.

    Validation layers (in order):
      1. Propagate upstream pre-validation failure.
      2. Required header presence check.
      3. Payment channel ID check (mandatory for session-based MPP).
      4. Payment amount format and positivity.
      5. Presented amount >= required STC cost.
      6. Replay protection on payment_reference (local fast-fail).
      7. Control-plane authorize (source of truth for session balance/status).

    Capture happens in the metering middleware *after* a successful downstream
    response.  This function only covers steps 1–7 (pre-request gate).
    """
    from payments.enforcement import PaymentEnforcementResult

    payment_reference = _normalize_header(headers.get("x-stocktrends-payment-reference"))
    payment_network = _normalize_header(headers.get("x-stocktrends-payment-network"))
    payment_token = _normalize_header(headers.get("x-stocktrends-payment-token"))
    payment_channel_id = _extract_payment_channel_id(headers)
    payment_amount_native = _parse_decimal(headers.get("x-stocktrends-payment-amount"))

    # 1. Propagate upstream pre-validation failure.
    if not validation_valid:
        return PaymentEnforcementResult(
            outcome="validation_failed",
            error_code=validation_error,
            error_detail=validation_detail,
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=payment_amount_native,
            payment_channel_id=payment_channel_id,
        )

    # 2. Required header presence check.
    missing = [h for h in MPP_REQUIRED_HEADERS if not _normalize_header(headers.get(h))]
    if missing:
        return PaymentEnforcementResult(
            outcome="validation_failed",
            error_code="missing_payment_headers",
            error_detail="Missing required MPP headers: " + ", ".join(sorted(missing)),
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=payment_amount_native,
            payment_channel_id=payment_channel_id,
        )

    # 3. Payment channel ID check (required for session-based MPP).
    if not payment_channel_id:
        return PaymentEnforcementResult(
            outcome="invalid_channel",
            error_code="missing_channel_id",
            error_detail=(
                "MPP payment requires a session channel identifier. "
                "Provide X-StockTrends-Payment-Channel-Id or X-Payment-Channel-Id."
            ),
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=payment_amount_native,
            payment_channel_id=None,
        )

    # 4. Payment amount format and positivity.
    if payment_amount_native is None:
        return PaymentEnforcementResult(
            outcome="validation_failed",
            error_code="invalid_payment_amount",
            error_detail="MPP payment amount is not a valid decimal.",
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=None,
            payment_channel_id=payment_channel_id,
        )

    if payment_amount_native <= Decimal("0"):
        return PaymentEnforcementResult(
            outcome="validation_failed",
            error_code="nonpositive_payment_amount",
            error_detail="MPP payment amount must be greater than zero.",
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=payment_amount_native,
            payment_channel_id=payment_channel_id,
        )

    # 5. Presented amount >= required STC cost.
    #    amount_usd is the STC cost resolved by the pricing engine (rail-agnostic).
    #    MPP amounts are expressed in STC-equivalent units (1 STC ≈ $1 USD).
    if amount_usd is not None and payment_amount_native < amount_usd:
        return PaymentEnforcementResult(
            outcome="insufficient_balance",
            error_code="insufficient_payment_amount",
            error_detail=(
                f"Presented MPP amount {payment_amount_native} STC is less than "
                f"the required {amount_usd} STC for this endpoint."
            ),
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=payment_amount_native,
            payment_channel_id=payment_channel_id,
        )

    # 6. Replay protection.
    if replay_checker and payment_reference and replay_checker(payment_reference):
        return PaymentEnforcementResult(
            outcome="authorization_failed",
            error_code="replay_detected",
            error_detail="MPP payment reference has already been used.",
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=payment_amount_native,
            payment_channel_id=payment_channel_id,
        )

    # 7. Control-plane authorize — source of truth for session balance/status.
    from payments.mpp_client import authorize_mpp_payment

    auth_result = authorize_mpp_payment(
        channel_id=payment_channel_id,
        payment_reference=payment_reference,
        requested_stc=amount_usd if amount_usd is not None else payment_amount_native,
        pricing_rule_id=pricing_rule_id,
        path=path,
        request_id=request_id,
    )

    if not auth_result.success:
        return PaymentEnforcementResult(
            outcome="authorization_failed",
            error_code=auth_result.error_code,
            error_detail=auth_result.error_detail,
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=payment_amount_native,
            payment_channel_id=payment_channel_id,
        )

    return PaymentEnforcementResult(
        outcome="authorized",
        payment_reference=payment_reference,
        payment_network=payment_network,
        payment_token=payment_token,
        payment_amount_native=payment_amount_native,
        payment_channel_id=payment_channel_id,
    )
