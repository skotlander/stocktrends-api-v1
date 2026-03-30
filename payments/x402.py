import os
import time
import json
import requests
import jwt
from typing import Any, Optional
from dataclasses import dataclass

# =========================
# ENV CONFIG
# =========================

X402_FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL", "").rstrip("/")
X402_API_KEY = os.getenv("X402_FACILITATOR_API_KEY")
X402_API_SECRET = os.getenv("X402_FACILITATOR_API_SECRET")
X402_TIMEOUT_SECONDS = int(os.getenv("X402_TIMEOUT_SECONDS", "10"))

X402_DEFAULT_NETWORK = os.getenv("X402_DEFAULT_NETWORK")
X402_DEFAULT_TOKEN = os.getenv("X402_DEFAULT_TOKEN")
X402_DEFAULT_TOKEN_NAME = os.getenv("X402_DEFAULT_TOKEN_NAME", "USDC")
X402_DEFAULT_TOKEN_VERSION = os.getenv("X402_DEFAULT_TOKEN_VERSION", "2")
X402_DEFAULT_ASSET_TRANSFER_METHOD = os.getenv(
    "X402_DEFAULT_ASSET_TRANSFER_METHOD", "eip3009"
)
X402_DEFAULT_SCHEME = os.getenv("X402_DEFAULT_SCHEME", "exact")
X402_SELLER_ADDRESS = os.getenv("X402_SELLER_ADDRESS")

USDC_DECIMALS = 6  # Base USDC

# =========================
# UTILITY
# =========================


def is_x402_payment_method(headers: dict) -> bool:
    """
    Detect if request is attempting x402 payment.
    """
    if not headers:
        return False

    # Standard header used by clients
    if "x-payment" in headers:
        return True

    # Fallback (some clients may use Authorization-style header)
    auth = headers.get("authorization", "")
    if auth.lower().startswith("x402"):
        return True

    return False
# =========================
# DATA STRUCTURE
# =========================

@dataclass
class X402ValidationResult:
    valid: bool
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    verification_response: Optional[dict] = None
    settlement_response: Optional[dict] = None


# =========================
# HELPERS
# =========================

def _usd_to_base_units(amount_usd: str) -> int:
    """
    Convert USD string to base units (USDC = 6 decimals)
    Example: "0.002500" → 2500
    """
    return int(float(amount_usd) * (10 ** USDC_DECIMALS))


def _build_jwt() -> str:
    """
    Coinbase facilitator JWT (ES256)
    """
    if not X402_API_KEY or not X402_API_SECRET:
        raise RuntimeError("Missing X402 facilitator credentials")

    secret = X402_API_SECRET.replace("\\n", "\n")

    payload = {
        "iss": X402_API_KEY,
        "sub": X402_API_KEY,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }

    return jwt.encode(payload, secret, algorithm="ES256")


def _post_json(url: str, body: dict[str, Any]):
    try:
        token = _build_jwt()

        res = requests.post(
            url,
            json=body,
            timeout=X402_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        try:
            data = res.json()
        except Exception:
            data = None

        return res.status_code, data, res.text

    except Exception as e:
        return 0, None, str(e)


# =========================
# REQUIREMENTS BUILDER
# =========================

def build_payment_requirements(resource: str, method: str, amount_usd: str) -> dict:
    """
    Build x402 v2 payment requirements
    """

    amount_base = _usd_to_base_units(amount_usd)

    return {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": X402_DEFAULT_SCHEME,
                "network": X402_DEFAULT_NETWORK,
                "resource": resource,
                "method": method,
                "maxAmountRequired": str(amount_base),
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


# =========================
# VERIFY
# =========================

def verify_with_facilitator(
    *,
    payment_signature: str,
    payment_requirements: dict[str, Any],
) -> X402ValidationResult:

    status, data, raw = _post_json(
        f"{X402_FACILITATOR_URL}/verify",
        {
            "x402Version": 2,
            "paymentHeader": payment_signature,
            "paymentRequirements": payment_requirements,
        },
    )

    if status == 0:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_unreachable",
            error_detail=raw,
        )

    if status >= 400:
        detail = f"Facilitator /verify returned HTTP {status}"
        if data:
            detail += f": {json.dumps(data)}"
        elif raw:
            detail += f": {raw}"

        return X402ValidationResult(
            valid=False,
            error_code="facilitator_verify_failed",
            error_detail=detail,
            verification_response=data,
        )

    if not data or not (data.get("valid") or data.get("isValid")):
        return X402ValidationResult(
            valid=False,
            error_code="payment_invalid",
            error_detail="Facilitator rejected payment",
            verification_response=data,
        )

    return X402ValidationResult(valid=True, verification_response=data)


# =========================
# SETTLE
# =========================

def settle_with_facilitator(
    *,
    payment_signature: str,
    payment_requirements: dict[str, Any],
) -> X402ValidationResult:

    status, data, raw = _post_json(
        f"{X402_FACILITATOR_URL}/settle",
        {
            "x402Version": 2,
            "paymentHeader": payment_signature,
            "paymentRequirements": payment_requirements,
        },
    )

    if status == 0:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_unreachable",
            error_detail=raw,
        )

    if status >= 400:
        detail = f"Facilitator /settle returned HTTP {status}"
        if data:
            detail += f": {json.dumps(data)}"
        elif raw:
            detail += f": {raw}"

        return X402ValidationResult(
            valid=False,
            error_code="facilitator_settle_failed",
            error_detail=detail,
            settlement_response=data,
        )

    if not data or not (
        data.get("success") or data.get("settled") or data.get("txHash")
    ):
        return X402ValidationResult(
            valid=False,
            error_code="settlement_failed",
            error_detail="Facilitator did not confirm settlement",
            settlement_response=data,
        )

    return X402ValidationResult(valid=True, settlement_response=data)