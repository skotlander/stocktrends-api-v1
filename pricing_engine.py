def resolve_pricing_rule(request_path: str, method: str):
    # Simplified pattern matching
    # In production: use cached rules + prefix matching

    if request_path.startswith("/v1/instruments"):
        return "public_instruments"

    if request_path.startswith("/v1/prices"):
        return "metered_prices"

    if request_path.startswith("/v1/selections"):
        return "selections_core"

    if request_path.startswith("/v1/stim"):
        return "stim_premium"

    return "default_public"