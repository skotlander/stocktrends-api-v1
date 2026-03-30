import os
import time
import json
import httpx
import jwt
from typing import Dict, Any

# =========================
# ENV CONFIG
# =========================

FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL")
FACILITATOR_API_KEY = os.getenv("X402_FACILITATOR_API_KEY")
FACILITATOR_API_SECRET = os.getenv("X402_FACILITATOR_API_SECRET")

DEFAULT_NETWORK = os.getenv("X402_DEFAULT_NETWORK")
DEFAULT_TOKEN = os.getenv("X402_DEFAULT_TOKEN")
DEFAULT_SCHEME = os.getenv("X402_DEFAULT_SCHEME", "exact")
SELLER_ADDRESS = os.getenv("X402_SELLER_ADDRESS")

TIMEOUT = int(os.getenv("X402_TIMEOUT_SECONDS", "10"))

# =========================
# UTIL
# =========================

def _load_private_key():
    if not FACILITATOR_API_SECRET:
        raise RuntimeError("Missing X402_FACILITATOR_API_SECRET")

    return FACILITATOR_API_SECRET.replace("\\n", "\n")


def _sign_jwt(payload: dict) -> str:
    key = _load_private_key()
    return jwt.encode(payload, key, algorithm="ES256")


def is_x402_payment_method(headers: dict) -> bool:
    if not headers:
        return False

    if headers.get("x-stocktrends-payment-method") == "x402":
        return True

    if "x-payment" in headers:
        return True

    auth = headers.get("authorization", "")
    if auth.lower().startswith("x402"):
        return True

    return False


# =========================
# BUILD PAYMENT RESPONSE (402)
# =========================

def build_payment_required(
    resource: str,
    method: str,
    amount_usd: float
) -> Dict[str, Any]:

    # Convert USD → USDC micro units (6 decimals)
    # 0.0025 → 2500
    amount = int(amount_usd * 1_000_000)

    return {
        "error": "payment_required",
        "detail": "Payment is required to access this endpoint.",
        "protocol": "x402",
        "resource": resource,
        "pricing": {
            "amount_usd": f"{amount_usd:.6f}",
            "unit": "request",
            "network": DEFAULT_NETWORK,
            "token": DEFAULT_TOKEN,
            "scheme": DEFAULT_SCHEME,
        },
        "accepted_payment_methods": ["x402"],
        "payment_required": {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": DEFAULT_SCHEME,
                    "network": DEFAULT_NETWORK,
                    "resource": resource,
                    "method": method,
                    "maxAmountRequired": str(amount),
                    "asset": DEFAULT_TOKEN,
                    "payTo": SELLER_ADDRESS,
                    "maxTimeoutSeconds": 300,
                    "extra": {
                        "name": "USDC",
                        "version": "2",
                        "assetTransferMethod": "eip3009",
                    },
                }
            ],
        },
    }


# =========================
# VERIFY PAYMENT
# =========================

async def verify_x402_payment(headers: dict) -> bool:
    """
    Verify payment with Coinbase facilitator
    """

    payment_header = headers.get("x-payment")
    if not payment_header:
        return False

    try:
        payment_data = json.loads(payment_header)
    except Exception:
        return False

    payload = {
        "payment": payment_data,
        "timestamp": int(time.time())
    }

    token = _sign_jwt(payload)

    verify_headers = {
        "Authorization": f"Bearer {FACILITATOR_API_KEY}",
        "X-Signature": token,
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{FACILITATOR_URL}/verify",
                headers=verify_headers,
                json=payload
            )

        if resp.status_code != 200:
            print("VERIFY ERROR:", resp.status_code, resp.text)
            return False

        data = resp.json()
        return data.get("valid", False)

    except Exception as e:
        print("VERIFY EXCEPTION:", str(e))
        return False