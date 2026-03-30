import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key


# =========================================================
# CONFIG
# =========================================================

X402_FACILITATOR_URL = os.getenv(
    "X402_FACILITATOR_URL",
    "https://api.cdp.coinbase.com/platform/v2/x402",
).rstrip("/")

X402_FACILITATOR_API_KEY = os.getenv("X402_FACILITATOR_API_KEY")
X402_FACILITATOR_API_SECRET = os.getenv("X402_FACILITATOR_API_SECRET")

X402_DEFAULT_NETWORK = os.getenv("X402_DEFAULT_NETWORK", "eip155:8453")
X402_DEFAULT_SCHEME = os.getenv("X402_DEFAULT_SCHEME", "exact")
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
X402_DEFAULT_TOKEN_DECIMALS = int(os.getenv("X402_DEFAULT_TOKEN_DECIMALS", "6"))
X402_SELLER_ADDRESS = os.getenv("X402_SELLER_ADDRESS", "")
X402_TIMEOUT_SECONDS = float(os.getenv("X402_TIMEOUT_SECONDS", "10"))


# =========================================================
# DATA STRUCTURES
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


def _to_atomic_units(amount: Decimal, decimals: int) -> str:
    quantized = (amount * (Decimal(10) ** decimals)).quantize(Decimal("1"))
    return str(int(quantized))


def _b64_json(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


def _decode_b64_json(value: str) -> dict[str, Any]:
    decoded = base64.b64decode(value)
    return json.loads(decoded.decode("utf-8"))


def _normalize_private_key(secret: str) -> str:
    secret = secret.strip()
    if "\\n" in secret:
        secret = secret.replace("\\n", "\n")
    return secret


def _build_cdp_bearer_token(method: str, url: str) -> str | None:
    if not X402_FACILITATOR_API_KEY or not X402_FACILITATOR_API_SECRET:
        return None

    now = int(time.time())
    parsed = urlparse(url)
    request_host = parsed.netloc
    request_path = parsed.path
    uri = f"{method.upper()} {request_host}{request_path}"

    private_key_pem = _normalize_private_key(X402_FACILITATOR_API_SECRET).encode("utf-8")
    private_key = load_pem_private_key(private_key_pem, password=None)

    payload = {
        "sub": X402_FACILITATOR_API_KEY,
        "iss": "cdp",
        "nbf": now,
        "exp": now + 120,
        "uri": uri,
    }

    headers = {
        "kid": X402_FACILITATOR_API_KEY,
        "nonce": uuid.uuid4().hex,
    }

    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers,
    )
    return token


def _facilitator_headers(method: str, url: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    bearer = _build_cdp_bearer_token(method, url)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def _post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str | None]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=data,
        headers=_facilitator_headers("POST", url),
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=X402_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(body) if body else {}
            except ValueError:
                parsed = None
            return resp.status, parsed, body
    except urllib_error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = str(e)
        try:
            parsed = json.loads(body) if body else {}
        except ValueError:
            parsed = None
        return e.code, parsed, body
    except Exception as e:
        return 0, None, str(e)


def _normalize_payment_requirements_input(payment_requirements: Any) -> Any:
    """
    Accepts:
    - already-parsed dict
    - JSON string
    - base64-encoded JSON string
    """
    if isinstance(payment_requirements, dict):
        return payment_requirements

    if isinstance(payment_requirements, str):
        value = payment_requirements.strip()

        # Try direct JSON first
        try:
            return json.loads(value)
        except Exception:
            pass

        # Then try base64 JSON
        try:
            return _decode_b64_json(value)
        except Exception:
            pass

    return payment_requirements


def _extract_single_payment_requirement(payment_requirements: Any) -> dict[str, Any]:
    """
    Facilitator expects one payment requirement object that directly contains
    keys like scheme/network/resource/method/amount/asset/payTo.

    This helper tolerates several shapes:
    - {"x402Version":2,"accepts":[{...}]}
    - {"payment_required":{"x402Version":2,"accepts":[{...}]}, ...}
    - base64/json string of either of the above
    - already-single requirement object
    """
    obj = _normalize_payment_requirements_input(payment_requirements)

    if not isinstance(obj, dict):
        return {}

    # Full 402 body case
    if "payment_required" in obj and isinstance(obj["payment_required"], (dict, str)):
        obj = _normalize_payment_requirements_input(obj["payment_required"])

    if not isinstance(obj, dict):
        return {}

    # Wrapper case
    accepts = obj.get("accepts")
    if isinstance(accepts, list) and accepts and isinstance(accepts[0], dict):
        return accepts[0]

    # Already single requirement case
    if "scheme" in obj:
        return obj

    return {}


# =========================================================
# HEADER / PAYMENT DETECTION HELPERS
# =========================================================

def is_x402_payment_method(headers_or_payment_method) -> bool:
    if headers_or_payment_method is None:
        return False

    if isinstance(headers_or_payment_method, str):
        return headers_or_payment_method.strip().lower() == "x402"

    headers = headers_or_payment_method
    payment_method = headers.get("x-stocktrends-payment-method", "")
    if isinstance(payment_method, str) and payment_method.strip().lower() == "x402":
        return True

    if headers.get("payment-signature"):
        return True

    if headers.get("x-payment"):
        return True

    auth = headers.get("authorization", "")
    if isinstance(auth, str) and auth.lower().startswith("x402"):
        return True

    return False


def has_payment_signature(headers) -> bool:
    return bool(headers.get("payment-signature"))


def extract_payment_signature(headers) -> Optional[str]:
    value = headers.get("payment-signature")
    if value:
        value = value.strip()
    return value or None


# =========================================================
# CORE BUILDERS
# =========================================================

def build_x402_requirements(
    *,
    path: str,
    amount_usd: Decimal,
    method: str = "GET",
) -> dict[str, Any]:
    return {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": X402_DEFAULT_SCHEME,
                "network": X402_DEFAULT_NETWORK,
                "resource": path,
                "method": method.upper(),
                "amount": _to_atomic_units(amount_usd, X402_DEFAULT_TOKEN_DECIMALS),
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
    amount_usd,
    method: str = "GET",
) -> tuple[dict[str, Any], str]:
    if not isinstance(amount_usd, Decimal):
        amount_usd = Decimal(str(amount_usd))

    requirements = build_x402_requirements(
        path=path,
        amount_usd=amount_usd,
        method=method,
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
            "network": X402_DEFAULT_NETWORK,
            "token": X402_DEFAULT_TOKEN,
            "scheme": X402_DEFAULT_SCHEME,
        },
        "accepted_payment_methods": ["x402"],
        "payment_required": requirements,
    }

    return body, payment_required_header


# =========================================================
# VALIDATION
# =========================================================

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
            error_detail=f"Could not decode PAYMENT-SIGNATURE: {e}",
        )

    amount_native: Optional[Decimal] = None
    payment_reference: Optional[str] = None
    payment_network: Optional[str] = None
    payment_token: Optional[str] = None

    if isinstance(payload, dict):
        payment_reference = str(
            payload.get("paymentIdentifier")
            or payload.get("payment_id")
            or payload.get("id")
            or signature
        )

        payment_network = (
            payload.get("network")
            or payload.get("chain")
            or payload.get("paymentNetwork")
        )

        payment_token = (
            payload.get("asset")
            or payload.get("token")
            or payload.get("paymentToken")
        )

        raw_amount = (
            payload.get("amount")
            or payload.get("maxAmountRequired")
            or payload.get("value")
            or payload.get("paymentAmount")
        )
        amount_native = _parse_decimal(str(raw_amount)) if raw_amount is not None else None

    required_amount_atomic = Decimal(
        _to_atomic_units(required_amount_usd, X402_DEFAULT_TOKEN_DECIMALS)
    )

    if amount_native is not None and amount_native < required_amount_atomic:
        return X402ValidationResult(
            valid=False,
            error_code="insufficient_payment_amount",
            error_detail=(
                f"Presented payment amount {amount_native} is less than "
                f"required amount {required_amount_atomic}."
            ),
            payment_signature=signature,
            payment_payload=payload,
            payment_reference=payment_reference,
            payment_network=payment_network,
            payment_token=payment_token,
            payment_amount_native=amount_native,
        )

    return X402ValidationResult(
        valid=True,
        payment_signature=signature,
        payment_payload=payload,
        payment_reference=payment_reference or signature,
        payment_network=payment_network,
        payment_token=payment_token,
        payment_amount_native=amount_native,
    )


# =========================================================
# FACILITATOR
# =========================================================

def verify_with_facilitator(
    *,
    payment_signature: str,
    payment_requirements: dict[str, Any],
) -> X402ValidationResult:
    single_requirement = _extract_single_payment_requirement(payment_requirements)

    status, data, raw = _post_json(
        f"{X402_FACILITATOR_URL}/verify",
        {
            "x402Version": 2,
            "paymentHeader": payment_signature,
            "paymentRequirements": single_requirement,
        },
    )

    if status == 0:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_verify_unreachable",
            error_detail=raw,
        )

    if status >= 400:
        detail = f"Facilitator /verify returned HTTP {status}"
        if data:
            detail = f"{detail}: {json.dumps(data)}"
        elif raw:
            detail = f"{detail}: {raw}"

        return X402ValidationResult(
            valid=False,
            error_code="facilitator_verify_failed",
            error_detail=detail,
            verification_response=data,
        )

    verified = bool((data or {}).get("isValid") or (data or {}).get("valid"))
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
    single_requirement = _extract_single_payment_requirement(payment_requirements)

    status, data, raw = _post_json(
        f"{X402_FACILITATOR_URL}/settle",
        {
            "x402Version": 2,
            "paymentHeader": payment_signature,
            "paymentRequirements": single_requirement,
        },
    )

    if status == 0:
        return X402ValidationResult(
            valid=False,
            error_code="facilitator_settle_unreachable",
            error_detail=raw,
        )

    if status >= 400:
        detail = f"Facilitator /settle returned HTTP {status}"
        if data:
            detail = f"{detail}: {json.dumps(data)}"
        elif raw:
            detail = f"{detail}: {raw}"

        return X402ValidationResult(
            valid=False,
            error_code="facilitator_settle_failed",
            error_detail=detail,
            settlement_response=data,
        )

    settled = bool(
        (data or {}).get("success")
        or (data or {}).get("settled")
        or (data or {}).get("txHash")
    )
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