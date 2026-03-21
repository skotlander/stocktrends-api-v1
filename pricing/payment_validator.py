from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional


@dataclass
class PaymentValidationResult:
    valid: bool
    error_code: Optional[str]
    error_detail: Optional[str]


REQUIRED_PAYMENT_HEADERS = {
    "x-stocktrends-payment-method",
    "x-stocktrends-payment-network",
    "x-stocktrends-payment-reference",
    "x-stocktrends-payment-amount",
}


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def validate_payment_headers(headers) -> PaymentValidationResult:
    missing = [h for h in REQUIRED_PAYMENT_HEADERS if not headers.get(h)]
    if missing:
        return PaymentValidationResult(
            valid=False,
            error_code="missing_payment_headers",
            error_detail="Missing required payment headers: " + ", ".join(sorted(missing)),
        )

    amount = _parse_decimal(headers.get("x-stocktrends-payment-amount"))
    if amount is None:
        return PaymentValidationResult(
            valid=False,
            error_code="invalid_payment_amount",
            error_detail="Payment amount is not a valid decimal.",
        )

    if amount <= 0:
        return PaymentValidationResult(
            valid=False,
            error_code="nonpositive_payment_amount",
            error_detail="Payment amount must be greater than zero.",
        )

    return PaymentValidationResult(
        valid=True,
        error_code=None,
        error_detail=None,
    )