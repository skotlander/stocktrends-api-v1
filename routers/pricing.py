from fastapi import APIRouter

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.get("")
def get_pricing():
    return {
        "version": "1",
        "endpoint_families": {
            "stim": {
                "pricing_model": "subscription_or_agent_pay",
                "pricing_rule_default": "default_subscription",
                "agent_pay_supported": True,
                "payment_required": False,
                "accepted_payment_methods": [
                    "subscription",
                    "mpp",
                    "x402",
                    "crypto",
                ],
                "payment_headers": [
                    "X-StockTrends-Payment-Method",
                    "X-StockTrends-Payment-Network",
                    "X-StockTrends-Payment-Reference",
                    "X-StockTrends-Payment-Amount",
                    "X-StockTrends-Payment-Token",
                    "X-StockTrends-Pricing-Rule",
                ],
                "agent_headers": [
                    "X-StockTrends-Agent-Id",
                    "X-StockTrends-Agent-Type",
                    "X-StockTrends-Agent-Vendor",
                    "X-StockTrends-Agent-Version",
                    "X-StockTrends-Request-Purpose",
                    "X-StockTrends-Session-Id",
                ],
                "notes": [
                    "STIM endpoints are currently subscription-covered by default.",
                    "Agent payment metadata is supported for discovery and logging.",
                    "Payment enforcement may be enabled in the future for selected routes.",
                ],
            },
            "ai": {
                "pricing_model": "free_metered",
                "pricing_rule_default": "default_free_metered",
                "payment_required": False,
            },
            "breadth": {
                "pricing_model": "mixed",
                "notes": [
                    "/v1/breadth/sector/latest is free-metered.",
                    "Other breadth endpoints may require subscription.",
                ],
            },
            "general_protected_api": {
                "pricing_model": "subscription",
                "pricing_rule_default": "default_subscription",
                "payment_required": False,
            },
            "public": {
                "pricing_model": "free",
                "pricing_rule_default": "default_free",
                "payment_required": False,
            },
        },
    }