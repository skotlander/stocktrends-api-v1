from __future__ import annotations

from decimal import Decimal, InvalidOperation


MPP_PAYMENT_CHANNEL_ID_HEADERS = (
    "x-stocktrends-payment-channel-id",
    "x-payment-channel-id",
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
    **_kwargs,
):
    from payments.enforcement import PaymentEnforcementResult

    payment_reference = _normalize_header(headers.get("x-stocktrends-payment-reference"))
    payment_network = _normalize_header(headers.get("x-stocktrends-payment-network"))
    payment_token = _normalize_header(headers.get("x-stocktrends-payment-token"))
    payment_channel_id = _extract_payment_channel_id(headers)
    payment_amount_native = _parse_decimal(headers.get("x-stocktrends-payment-amount"))

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

    return PaymentEnforcementResult(
        outcome="proceed",
        payment_reference=payment_reference,
        payment_network=payment_network,
        payment_token=payment_token,
        payment_amount_native=payment_amount_native,
        payment_channel_id=payment_channel_id,
    )
