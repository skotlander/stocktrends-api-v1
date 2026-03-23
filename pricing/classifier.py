from dataclasses import dataclass
import os

ENABLE_AGENT_PAY = os.getenv("ENABLE_AGENT_PAY", "false").lower() == "true"
ENFORCE_AGENT_PAY = os.getenv("ENFORCE_AGENT_PAY", "false").lower() == "true"
VALIDATE_AGENT_PAY_HEADERS = os.getenv("VALIDATE_AGENT_PAY_HEADERS", "true").lower() == "true"


@dataclass
class PricingDecision:
    is_metered: int

    # access / policy layer
    access_granted: bool
    deny_reason: str | None

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


def _free_decision() -> PricingDecision:
    return PricingDecision(
        is_metered=0,
        access_granted=True,
        deny_reason=None,
        log_pricing_rule_id="default_free",
        log_payment_method="none",
        econ_pricing_rule_id=None,
        econ_payment_required=0,
        econ_payment_status=None,
        econ_payment_method=None,
    )


def _free_metered_decision() -> PricingDecision:
    return PricingDecision(
        is_metered=1,
        access_granted=True,
        deny_reason=None,
        log_pricing_rule_id="default_free_metered",
        log_payment_method="free",
        econ_pricing_rule_id="default_free_metered",
        econ_payment_required=0,
        econ_payment_status="not_required",
        econ_payment_method="free",
    )


def _subscription_decision() -> PricingDecision:
    return PricingDecision(
        is_metered=1,
        access_granted=True,
        deny_reason=None,
        log_pricing_rule_id="default_subscription",
        log_payment_method="subscription",
        econ_pricing_rule_id="default_subscription",
        econ_payment_required=0,
        econ_payment_status="not_required",
        econ_payment_method="subscription",
    )


def _agent_pay_decision() -> PricingDecision:
    return PricingDecision(
        is_metered=1,
        access_granted=True,
        deny_reason=None,
        log_pricing_rule_id="agent_pay_required",
        log_payment_method="mpp",
        econ_pricing_rule_id="agent_pay_required",
        econ_payment_required=1,
        econ_payment_status="pending",
        econ_payment_method="mpp",
    )


def _deny_decision(reason: str = "access_denied") -> PricingDecision:
    return PricingDecision(
        is_metered=1,
        access_granted=False,
        deny_reason=reason,
        log_pricing_rule_id="default_subscription",
        log_payment_method="subscription",
        econ_pricing_rule_id="default_subscription",
        econ_payment_required=0,
        econ_payment_status="not_required",
        econ_payment_method="subscription",
    )


def classify_request(
    path: str,
    has_paid_auth: bool,
    payment_method_header: str | None = None,
    plan_code: str | None = None,
) -> PricingDecision:
    """
    Classify request into pricing / metering tiers.

    Phase 4 STIM policy:
    - Public/static/docs paths are non-metered
    - Explicit free-metered API routes are tracked but not billed
    - /v1/stim*:
        * payment headers present => agent-pay
        * paid entitled customer without payment headers => subscription
        * otherwise => deny
    - Other /v1/* routes are subscription-backed
    - Non-/v1 probe traffic is never treated as paid API usage
    """

    if path in NON_METERED_PATHS:
        return _free_decision()

    if _is_noise_path(path):
        return _free_decision()

    if path in FREE_METERED_PATHS:
        return _free_metered_decision()

    is_stim = any(path.startswith(prefix) for prefix in AGENT_PAY_PATH_PREFIXES)
    has_payment_headers = bool(payment_method_header)

    if is_stim:
        # Explicit agent-pay intent.
        if ENABLE_AGENT_PAY and has_payment_headers:
            return _agent_pay_decision()

        # Subscription-entitled caller.
        if has_paid_auth and plan_code not in (None, "", "sandbox"):
            return _subscription_decision()

        # Everyone else is denied.
        if plan_code == "sandbox":
            return _deny_decision("sandbox_plan_denied")
        if not has_paid_auth:
            return _deny_decision("authentication_required")
        return _deny_decision("stim_access_not_permitted")

    if path.startswith("/v1/"):
        return _subscription_decision()

    return _free_decision()