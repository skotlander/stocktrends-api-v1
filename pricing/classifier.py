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
    "/v1/pricing",
}

FREE_METERED_PATHS = {
    "/v1/ai/context",
    "/v1/breadth/sector/latest",
}

AGENT_PAY_PATH_PREFIXES = {
    "/v1/stim",
}

# Non-API probe/scanner traffic that should never be treated as billable API usage.
NON_API_NOISE_PREFIXES = {
    "/cdn-cgi/",
    "/.well-known/",
    "/autodiscover/",
    "/owa/",
    "/SDK/",
    "/sdk/",
    "/wp-",
    "/wordpress",
    "/phpmyadmin",
}

NON_API_NOISE_EXACT_PATHS = {
    "/jobs",
    "/favicon.ico",
}


def _is_noise_path(path: str) -> bool:
    if path in NON_API_NOISE_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in NON_API_NOISE_PREFIXES)


def classify_request(path: str, has_paid_auth: bool) -> PricingDecision:
    """
    Classify request into pricing / metering tiers.

    Rules:
    - Explicit public/static/docs paths are non-metered
    - Explicit free-metered API routes are tracked but not billed
    - /v1/stim* can become agent-pay when enabled
    - Other /v1/* routes are subscription-backed
    - Non-/v1 probe traffic is never treated as paid API usage
    """

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

    if _is_noise_path(path):
        return PricingDecision(
            is_metered=0,
            log_pricing_rule_id="default_free",
            log_payment_method="none",
            econ_pricing_rule_id=None,
            econ_payment_required=0,
            econ_payment_status=None,
            econ_payment_method=None,
        )

    if path in FREE_METERED_PATHS:
        return PricingDecision(
            is_metered=1,
            log_pricing_rule_id="default_free_metered",
            log_payment_method="free",
            econ_pricing_rule_id="default_free_metered",
            econ_payment_required=0,
            econ_payment_status="not_required",
            econ_payment_method="free",
        )

    if ENABLE_AGENT_PAY and any(path.startswith(prefix) for prefix in AGENT_PAY_PATH_PREFIXES):
        return PricingDecision(
            is_metered=1,
            log_pricing_rule_id="agent_pay_required",
            log_payment_method="mpp",
            econ_pricing_rule_id="agent_pay_required",
            econ_payment_required=1,
            econ_payment_status="pending",
            econ_payment_method="mpp",
        )

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

    return PricingDecision(
        is_metered=0,
        log_pricing_rule_id="default_free",
        log_payment_method="none",
        econ_pricing_rule_id=None,
        econ_payment_required=0,
        econ_payment_status=None,
        econ_payment_method=None,
    )