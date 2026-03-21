from dataclasses import dataclass
import os

ENABLE_AGENT_PAY = os.getenv("ENABLE_AGENT_PAY", "false").lower() == "true"
ENFORCE_AGENT_PAY = os.getenv("ENFORCE_AGENT_PAY", "false").lower() == "true"
VALIDATE_AGENT_PAY_HEADERS = os.getenv("VALIDATE_AGENT_PAY_HEADERS", "true").lower() == "true"


@dataclass
class PricingDecision:
    is_metered: int

    # logging layer
    log_pricing_rule_id: str | None
    log_payment_method: str | None

    # economics layer
    econ_pricing_rule_id: str | None
    econ_payment_required: int
    econ_payment_status: str | None
    econ_payment_method: str | None


# -----------------------------
# CONFIGURATION
# -----------------------------

NON_METERED_PATHS = {
    "/",
    "/index.html",
    "/llms.txt",
    "/ai-dataset.json",
    "/tools.json",
    "/sitemap.xml",
    "/robots.txt",
    "/docs",
    "/v1/docs",
    "/openapi.json",
    "/v1/openapi.json",
    "/health",
    "/favicon.ico",
}

FREE_METERED_PATHS = {
    "/v1/ai/context",
    "/v1/breadth/sector/latest",
}

# Future premium / agent-pay endpoints
AGENT_PAY_PATH_PREFIXES = {
    "/v1/stim",
}

# Feature flag (OFF for now)
ENABLE_AGENT_PAY = False
ENFORCE_AGENT_PAY = False
VALIDATE_AGENT_PAY_HEADERS = True


# -----------------------------
# CLASSIFIER
# -----------------------------

def classify_request(path: str, has_paid_auth: bool) -> PricingDecision:
    """
    Classify request into pricing / metering tiers.

    IMPORTANT DESIGN:
    - Path-first classification (NOT auth-first)
    - /v1/* = economic surface
    - Auth only affects access, not pricing classification
    """

    # ----------------------------------------
    # 1. PUBLIC / NON-METERED
    # ----------------------------------------
    if path in NON_METERED_PATHS:
        return PricingDecision(
            is_metered=0,
            log_pricing_rule_id="default_free",
            log_payment_method="none",
            econ_pricing_rule_id=None,
            econ_payment_required=0,
            econ_payment_status=None,
            econ_payment_method=None,
        )

    # ----------------------------------------
    # 2. FREE BUT METERED (ANALYTICS VALUE)
    # ----------------------------------------
    if path in FREE_METERED_PATHS:
        return PricingDecision(
            is_metered=1,
            log_pricing_rule_id="default_free_metered",
            log_payment_method="none",
            econ_pricing_rule_id="default_free_metered",
            econ_payment_required=0,
            econ_payment_status="not_required",
            econ_payment_method="free",
        )

    # ----------------------------------------
    # 3. FUTURE: AGENT PAY (MPP / x402)
    # ----------------------------------------
    if ENABLE_AGENT_PAY and any(path.startswith(p) for p in AGENT_PAY_PATH_PREFIXES):
        return PricingDecision(
            is_metered=1,
            log_pricing_rule_id="agent_pay_required",
            log_payment_method="mpp",
            econ_pricing_rule_id="agent_pay_required",
            econ_payment_required=1,
            econ_payment_status="pending",
            econ_payment_method="mpp",
        )

    # ----------------------------------------
    # 4. DEFAULT: ALL /v1/* IS SUBSCRIPTION
    # ----------------------------------------
    if path.startswith("/v1/"):
        return PricingDecision(
            is_metered=1,
            log_pricing_rule_id="default_subscription",
            log_payment_method="subscription",
            econ_pricing_rule_id="default_subscription",
            econ_payment_required=0,
            econ_payment_status="not_required",
            econ_payment_method="subscription",
        )

    # ----------------------------------------
    # 5. FALLBACK (SAFE DEFAULT)
    # ----------------------------------------
    return PricingDecision(
        is_metered=0,
        log_pricing_rule_id="default_free",
        log_payment_method="none",
        econ_pricing_rule_id=None,
        econ_payment_required=0,
        econ_payment_status=None,
        econ_payment_method=None,
    )