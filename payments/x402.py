import base64
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from urllib import request as urllib_request
from urllib import error as urllib_error


# =========================================================
# CONFIG
# =========================================================

X402_FACILITATOR_URL = os.getenv(
    "X402_FACILITATOR_URL",
    "https://api.cdp.coinbase.com/platform/v2/x402",
).rstrip("/")

X402_FACILITATOR_API_KEY = os.getenv("X402_FACILITATOR_API_KEY")
X402_FACILITATOR_API_SECRET = os.getenv("X402_FACILITATOR_API_SECRET")

# ✅ CRITICAL FIXES
X402_DEFAULT_NETWORK = os.getenv("X402_DEFAULT_NETWORK", "eip155:8453")  # Base mainnet
X402_DEFAULT_SCHEME = os.getenv("X402_DEFAULT_SCHEME", "exact")

# Base USDC (native)
X402_DEFAULT_TOKEN = os.getenv(
    "X402_DEFAULT_TOKEN",
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
)

X402_DEFAULT_TOKEN_NAME = os.getenv("X402_DEFAULT_TOKEN_NAME", "USDC")
X402_DEFAULT_TOKEN_VERSION = os.getenv("X402_DEFAULT_TOKEN_VERSION", "2")
X402_DEFAULT_ASSET_TRANSFER_METHOD = os.getenv(
    "X402_DEFAULT_ASSET_TRANSFER_METHOD",
    "eip3009",
)

X402_SELLER_ADDRESS = os.getenv("X402_SELLER_ADDRESS", "")
X402_TIMEOUT_SECONDS = float(os.getenv("X402_TIMEOUT_SECONDS", "10"))


# =========================================================
# DATA STRUCTURE
# =========================================================

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


# =========================================================
# HELPERS
# =========================================================

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
    headers = {"Content-Type": "application/json"}
    if X402_FACILITATOR_API_KEY:
        headers["x-api-key"] = X402_FACILITATOR_API_KEY
    if X402_FACILITATOR_API_SECRET:
        headers["x-api-secret"] = X402_FACILITATOR_API_SECRET
    return headers


def _post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str | None]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=data,
        headers=_facilitator_headers(),
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=X402_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}, body
    except urllib_error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except:
            parsed = None
        return e.code, parsed, body
    except Exception as e:
        return 0, None, str(e)


# =========================================================
# CORE BUILDERS (FIXED)
# =========================================================

def build_x402_requirements(
    *,
    path: str,
    amount_usd: Decimal,
    method: str = "GET",
) -> dict[str, Any]:

    return {
        "x402Version": 1,
        "accepts": [
            {
                "scheme": X402_DEFAULT_SCHEME,
                "network": X402_DEFAULT_NETWORK,
                "resource": path,
                "method": method.upper(),
                "maxAmountRequired": f"{amount_usd:.6f}",
                "asset": X402_DEFAULT_TOKEN,
                "payTo": X402_SELLER_ADDRESS,
                "maxTimeoutSeconds": 300,
                "extra": {
                    "name": X402_DEFAULT_TOKEN_NAME,
                    "version": X402_DEFAULT_TOKEN_VERSION,
                    "assetTransferMethod": X402_DEFAULT_ASSET_TRANSFER_METHOD,
                },
            }
        ],
    }


def build_x402_challenge(
    *,
    path: str,
    amount_usd: Decimal,
    method: str = "GET",
) -> tuple[dict[str, Any], str]:

    requirements = build_x402_requirements(
        path=path,
        amount_usd=amount_usd,
        method=method,
    )

    header = _b64_json(requirements)

    body = {
        "error": "payment_required",
        "detail": "Payment is required to access this endpoint.",
        "protocol": "x402",
        "resource": path,
        "pricing": {
            "amount_usd": f"{amount_usd:.6f}",
            "unit": "request",
            "network": X402_DEFAULT_NETWORK,
            "token": X402_DEFAULT_TOKEN,
            "scheme": X402_DEFAULT_SCHEME,
        },
        "accepted_payment_methods": ["x402"],
        "payment_required": requirements,
    }

    return body, header


# =========================================================
# VALIDATION
# =========================================================

def is_x402_payment_method(payment_method: str | None) -> bool:
    return (payment_method or "").strip().lower() == "x402"


def has_payment_signature(headers) -> bool:
    return bool(headers.get("payment-signature"))

def extract_payment_signature(headers) -> Optional[str]:
    value = headers.get("payment-signature")
    return value.strip() if value else None


def validate_x402_payment(
    headers,
    *,
    required_amount_usd: Decimal,
) -> X402ValidationResult:

    signature = extract_payment_signature(headers)

    if not signature:
        return X402ValidationResult(
            valid=False,
            error_code="missing_payment_signature",
            error_detail="PAYMENT-SIGNATURE header is required.",
        )

    try:
        payload = _decode_b64_json(signature)
    except Exception as e:
        return X402ValidationResult(
            valid=False,
            error_code="invalid_payment_signature",
            error_detail=str(e),
        )

    return X402ValidationResult(
        valid=True,
        payment_signature=signature,
        payment_payload=payload,
    )


# =========================================================
# FACILITATOR
# =========================================================

def verify_with_facilitator(
    *,
    payment_signature: str,
    payment_requirements: dict[str, Any],
) -> X402ValidationResult:

    status, data, raw = _post_json(
        f"{X402_FACILITATOR_URL}/verify",
        {
            "x402Version": 1,
            "paymentHeader": payment_signature,
            "paymentRequirements": payment_requirements,
        },
    )

    if status >= 400:
        return X402ValidationResult(
            valid=False,
            error_code="verify_failed",
            error_detail=str(data),
        )

    return X402ValidationResult(valid=True, verification_response=data)


def settle_with_facilitator(
    *,
    payment_signature: str,
    payment_requirements: dict[str, Any],
) -> X402ValidationResult:

    status, data, raw = _post_json(
        f"{X402_FACILITATOR_URL}/settle",
        {
            "x402Version": 1,
            "paymentHeader": payment_signature,
            "paymentRequirements": payment_requirements,
        },
    )

    if status >= 400:
        return X402ValidationResult(
            valid=False,
            error_code="settle_failed",
            error_detail=str(data),
        )

    return X402ValidationResult(valid=True, settlement_response=data)