from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional


@dataclass
class X402ValidationResult:
    valid: bool
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_network: Optional[str] = None
    payment_token: Optional[str] = None
    payment_amount_native: Optional[Decimal] = None


REQUIRED_X402_HEADERS = {
    "x-stocktrends-payment-reference",
    "x-stocktrends-payment-amount",
    "x-stocktrends-payment-network",
}


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def is_x402_payment_method(payment_method: str | None) -> bool:
    return (payment_method or "").strip().lower() == "x402"


def build_x402_challenge(
    *,
    path: str,
    amount_usd: Decimal,
    network: str = "base",
    token: str = "usdc",
) -> dict:
    return {
        "error": "payment_required",
        "detail": "Payment is required to access this endpoint.",
        "protocol": "x402",
        "resource": path,
        "pricing": {
            "amount_usd": f"{amount_usd:.6f}",
            "unit": "request",
            "network": network,
            "token": token,
        },
        "accepted_payment_methods": ["x402"],
    }


def validate_x402_payment(
    headers,
    *,
    required_amount_usd: Decimal,
) -> X402ValidationResult:
    missing = [h for h in REQUIRED_X402_HEADERS if not headers.get(h)]
    if missing:
        return X402ValidationResult(
            valid=False,
            error_code="missing_payment_headers",
            error_detail="Missing required x402 headers: " + ", ".join(sorted(missing)),
        )

    amount_native = _parse_decimal(headers.get("x-stocktrends-payment-amount"))
    if amount_native is None:
        return X402ValidationResult(
            valid=False,
            error_code="invalid_payment_amount",
            error_detail="Payment amount is not a valid decimal.",
        )

    if amount_native <= 0:
        return X402ValidationResult(
            valid=False,
            error_code="nonpositive_payment_amount",
            error_detail="Payment amount must be greater than zero.",
        )

    if amount_native < required_amount_usd:
        return X402ValidationResult(
            valid=False,
            error_code="insufficient_payment_amount",
            error_detail=(
                f"Presented payment amount {amount_native} is less than "
                f"required amount {required_amount_usd}."
            ),
            payment_amount_native=amount_native,
        )

    return X402ValidationResult(
        valid=True,
        error_code=None,
        error_detail=None,
        payment_reference=headers.get("x-stocktrends-payment-reference"),
        payment_network=headers.get("x-stocktrends-payment-network"),
        payment_token=headers.get("x-stocktrends-payment-token"),
        payment_amount_native=amount_native,
    )