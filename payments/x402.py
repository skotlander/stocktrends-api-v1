import os
import json
import httpx
import jwt

X402_FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL")
X402_API_KEY = os.getenv("X402_FACILITATOR_API_KEY")
X402_API_SECRET = os.getenv("X402_FACILITATOR_API_SECRET")


# --------------------------------------------------
# 🔐 JWT SIGNING
# --------------------------------------------------

def _get_private_key():
    if not X402_API_SECRET:
        raise RuntimeError("Missing X402_FACILITATOR_API_SECRET")

    return X402_API_SECRET.replace("\\n", "\n")


def _sign_jwt():
    private_key = _get_private_key()

    token = jwt.encode(
        {"iss": X402_API_KEY},
        private_key,
        algorithm="ES256"
    )

    return token


# --------------------------------------------------
# 📦 HEADER EXTRACTION (CRITICAL FIX)
# --------------------------------------------------

def extract_payment_headers(request):
    payload_raw = request.headers.get("X-PAYMENT-PAYLOAD")
    requirements_raw = request.headers.get("X-PAYMENT-REQUIREMENTS")

    if not payload_raw or not requirements_raw:
        raise ValueError("Missing x402 headers")

    try:
        payment_payload = json.loads(payload_raw)
        payment_requirements = json.loads(requirements_raw)
    except Exception as e:
        raise ValueError(f"Invalid JSON in headers: {e}")

    return payment_payload, payment_requirements


# --------------------------------------------------
# 💰 VERIFY WITH FACILITATOR
# --------------------------------------------------

async def verify_with_facilitator(request):

    payment_payload, payment_requirements = extract_payment_headers(request)

    # 🚨 DO NOT MODIFY STRUCTURE
    # Use EXACT object from client
    if isinstance(payment_requirements, list):
        payment_requirement = payment_requirements[0]
    else:
        payment_requirement = payment_requirements

    verify_body = {
        "paymentPayload": payment_payload,
        "paymentRequirements": payment_requirement
    }

    # 🔍 DEBUG (keep temporarily)
    print("DEBUG paymentPayload =", json.dumps(payment_payload, indent=2))
    print("DEBUG paymentRequirements =", json.dumps(payment_requirement, indent=2))

    headers = {
        "Authorization": f"Bearer {_sign_jwt()}",
        "Content-Type": "application/json"
    }

    url = f"{X402_FACILITATOR_URL}/verify"

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=verify_body, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Facilitator /verify returned HTTP {response.status_code}: {response.text}")

    data = response.json()

    if not data.get("isValid"):
        raise Exception(f"x402 invalid: {data}")

    return True