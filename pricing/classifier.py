from dataclasses import dataclass


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


@dataclass
class PricingDecision:
    is_metered: int
    log_pricing_rule_id: str | None
    log_payment_method: str | None
    econ_pricing_rule_id: str | None
    econ_payment_required: int
    econ_payment_status: str | None
    econ_payment_method: str | None


def classify_request(path: str, has_paid_auth: bool) -> PricingDecision:

    # 1. Explicit public / non-metered
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

    # 2. Explicit free-metered
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

    # 3. ALL /v1/ endpoints are metered API surface
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

    # 4. fallback
    return PricingDecision(
        is_metered=0,
        log_pricing_rule_id="default_free",
        log_payment_method="none",
        econ_pricing_rule_id=None,
        econ_payment_required=0,
        econ_payment_status=None,
        econ_payment_method=None,
    )