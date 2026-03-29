import base64
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import requests


X402_FACILITATOR_URL = os.getenv(
    "X402_FACILITATOR_URL",
    "https://api.cdp.coinbase.com/platform/v2/x402",
).rstrip("/")

X402_FACILITATOR_API_KEY = os.getenv("X402_FACILITATOR_API_KEY")
X402_FACILITATOR_API_SECRET = os.getenv("X402_FACILITATOR_API_SECRET")
X402_DEFAULT_NETWORK = os.getenv("X402_DEFAULT_NETWORK", "base")
X402_DEFAULT_TOKEN = os.getenv("X402_DEFAULT_TOKEN", "usdc")
X402_DEFAULT_SCHEME = os.getenv("X402_DEFAULT_SCHEME", "exact")
X402_SELLER_ADDRESS = os.getenv("X402_SELLER_ADDRESS", "")
X402_TIMEOUT_SECONDS = float(os.getenv("X402_TIMEOUT_SECONDS", "10"))


@dataclass
class X402ValidationResult:
    valid: bool
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_network: Optional[str] = None
    payment_token: Optional[str] = None
    payment_amount_native: Optional[Decimal] = None
    payment_signature: Optional[str] = None
    payment_payload: Optional[dict[str, Any]] = None
    verification_response: Optional[dict[str, Any]] = None
    settlement_response: Optional[dict[str, Any]] = None


REQUIRED_STOCKTRENDS_X402_HEADERS = {
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


def _b64_json(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


def _decode_b64_json(value: str) -> dict[str, Any]:
    decoded = base64.b64decode(value)
    return json.loads(decoded.decode("utf-8"))


def _facilitator_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }

    if X402_FACILITATOR_API_KEY:
        headers["x-api-key"] = X402_FACILITATOR_API_KEY

    if X402_FACILITATOR_API_SECRET:
        headers["x-api-secret"] = X402_FACILITATOR_API_SECRET

    return headers


def is_x402_payment_method(payment_method: str | None) -> bool:
    return (payment_method or "").strip().lower() == "x402"


def has_payment_signature(headers) -> bool:
    return bool(headers.get("payment-signature"))


def extract_payment_signature(headers) -> Optional[str]:
    value = headers.get("payment-signature")
    if value:
        value = value.strip()
    return value or None


def build_x402_requirements(
    *,
    path: str,
    amount_usd: Decimal,
    method: str = "GET",
    network: str = X402_DEFAULT_NETWORK,
    token: str = X402_DEFAULT_TOKEN,
    scheme: str = X402_DEFAULT_SCHEME,
    pay_to: str = X402_SELLER_ADDRESS,
    max_timeout_seconds: int = 300,
) -> dict[str, Any]:
    """
    Builds a pragmatic payment requirements object for x402 challenge/verification.

    This is the object we will:
    - include in the response body for human inspection
    - base64-encode into PAYMENT-REQUIRED for compliant x402 clients
    - send to facilitator /verify and /settle once you switch to full verification
    """
    return {
        "x402Version": 1,
        "accepts": [
            {
                "scheme": scheme,
                "network": network,
                "resource": path,
                "method": method.upper(),
                "maxAmountRequired": str(amount_usd),
                "asset": token.lower(),
                "payTo": pay_to,
                "maxTimeoutSeconds": max_timeout_seconds,
            }
        ],
    }


def build_x402_challenge(
    *,
    path: str,
    amount_usd: Decimal,
    method: str = "GET",
    network: str = X402_DEFAULT_NETWORK,
    token: str = X402_DEFAULT_TOKEN,
    scheme: str = X402_DEFAULT_SCHEME,
    pay_to: str = X402_SELLER_ADDRESS,
) -> tuple[dict[str, Any], str]:
    requirements = build_x402_requirements(
        path=path,
        amount_usd=amount_usd,
        method=method,
        network=network,
        token=token,
        scheme=scheme,
        pay_to=pay_to,
    )

    payment_required_header = _b64_json(requirements)

    body = {
        "error": "payment_required",
        "detail": "Payment is required to access this endpoint.",
        "protocol": "x402",
        "resource": path,
        "pricing": {
            "amount_usd": f"{amount_usd:.6f}",
            "unit": "request",
            "network": network,
            "token": token,
            "scheme": scheme,
        },
        "accepted_payment_methods": ["x402"],
        "payment_required": requirements,
    }

    return body, payment_required_header


def validate_stocktrends_x402_headers(
    headers,
    *,
    required_amount_usd: Decimal,
) -> X402ValidationResult:
    """
    Backward-compatible validator for your current Stock Trends transitional headers.
    Keep this until your clients switch to official PAYMENT-SIGNATURE flow.
    """
    missing = [h for h in REQUIRED_STOCKTRENDS_X402_HEADERS if not headers.get(h)]
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
        payment_reference=headers.get("x-stocktrends-payment-reference"),
        payment_network=headers.get("x-stocktrends-payment-network"),
        payment_token=headers.get("x-stocktrends-payment-token"),
        payment_amount_native=amount_native,
    )


def validate_x402_payment(
    headers,
    *,
    required_amount_usd: Decimal,
) -> X402ValidationResult:
    """
    Transitional validator:
    - prefers official PAYMENT-SIGNATURE if present
    - otherwise falls back to Stock Trends compatibility headers
    """
    signature = extract_payment_signature(headers)
    if signature:
        try:
            payload = _decode_b64_json(signature)
        except Exception as e:
            return X402ValidationResult(
                valid=False,
                error_code="invalid_payment_signature",
                error_detail=f"Could not decode PAYMENT-SIGNATURE: {e}",
            )

        return X402ValidationResult(
            valid=True,
            payment_signature=signature,
            payment_payload=payload,
        )

    return validate_stocktrends_x402_headers(
        headers,
        required_amount_usd=required_amount_usd,
    )


def verify_with_facilitator(
    *,
    payment_signature: str,
    payment_requirements: dict[str, Any],
) -> X402ValidationResult:
    """
    Full x402 verification path via facilitator /verify.
    """
    try:
        resp = requests.post(
            f"{X402_FACILITATOR_URL}/verify",
            headers=_facilitator_headers(),
            json={
                "x402Version": 1,
                "paymentHeader": payment_signature,
                "paymentRequirements": payment_requirements,
            },
            timeout=X402_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_verify_unreachable",
            error_detail=str(e),
        )

    if resp.status_code >= 400:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_verify_failed",
            error_detail=f"Facilitator /verify returned HTTP {resp.status_code}",
        )

    try:
        data = resp.json()
    except ValueError:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_verify_invalid_json",
            error_detail="Facilitator /verify returned non-JSON response.",
        )

    verified = bool(data.get("isValid") or data.get("valid"))
    if not verified:
        return X402ValidationResult(
            valid=False,
            error_code="payment_verification_failed",
            error_detail="Facilitator reported invalid payment payload.",
            verification_response=data,
        )

    return X402ValidationResult(
        valid=True,
        verification_response=data,
    )


def settle_with_facilitator(
    *,
    payment_signature: str,
    payment_requirements: dict[str, Any],
) -> X402ValidationResult:
    """
    Full x402 settlement path via facilitator /settle.
    """
    try:
        resp = requests.post(
            f"{X402_FACILITATOR_URL}/settle",
            headers=_facilitator_headers(),
            json={
                "x402Version": 1,
                "paymentHeader": payment_signature,
                "paymentRequirements": payment_requirements,
            },
            timeout=X402_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_settle_unreachable",
            error_detail=str(e),
        )

    if resp.status_code >= 400:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_settle_failed",
            error_detail=f"Facilitator /settle returned HTTP {resp.status_code}",
        )

    try:
        data = resp.json()
    except ValueError:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_settle_invalid_json",
            error_detail="Facilitator /settle returned non-JSON response.",
        )

    settled = bool(data.get("success") or data.get("settled") or data.get("txHash"))
    if not settled:
        return X402ValidationResult(
            valid=False,
            error_code="payment_settlement_failed",
            error_detail="Facilitator did not confirm settlement.",
            settlement_response=data,
        )

    return X402ValidationResult(
        valid=True,
        settlement_response=data,
    )