# (imports unchanged)

# ADD THIS HELPER (place after resolve_economic_amounts)

def build_econ_payment_fields(
    payment_required: int,
    payment_status: str,
    payment_method_header: str | None,
    payment_network_header: str | None,
    payment_token_header: str | None,
    payment_amount_header: str | None,
    payment_reference_header: str | None,
    decision,
) -> dict:
    """
    Prevent pollution of economics table for non-required requests.
    """

    if not payment_required:
        return {
            "payment_status": "not_required",
            "payment_method": decision.econ_payment_method,
            "payment_network": None,
            "payment_token": None,
            "payment_amount_native": None,
            "payment_amount_usd": None,
            "payment_reference": None,
        }

    amount_native = None
    if payment_amount_header:
        try:
            amount_native = float(payment_amount_header)
        except:
            amount_native = None

    return {
        "payment_status": payment_status,
        "payment_method": payment_method_header or decision.econ_payment_method,
        "payment_network": payment_network_header,
        "payment_token": payment_token_header,
        "payment_amount_native": amount_native,
        "payment_amount_usd": None,
        "payment_reference": payment_reference_header,
    }


# =========================
# 🔁 ONLY CHANGE BELOW ARE ECON BLOCKS
# =========================


# 🔴 UPDATE 402 BLOCK ECON

# FIND THIS BLOCK (inside enforcement section)
# and REPLACE econ = {...} with:

econ_payment_fields = build_econ_payment_fields(
    payment_required=1,
    payment_status="failed_validation",
    payment_method_header=payment_method_header,
    payment_network_header=payment_network_header,
    payment_token_header=payment_token_header,
    payment_amount_header=payment_amount_header,
    payment_reference_header=payment_reference_header,
    decision=decision,
)

econ = {
    "request_id": request_id,
    "customer_id": getattr(request.state, "customer_id", None),
    "api_key_id": getattr(request.state, "api_key_id", None),
    "pricing_rule_id": economic_rule_name,
    "unit_price_usd": unit_price_usd,
    "billed_amount_usd": billed_amount_usd,
    "payment_required": 1,
    **econ_payment_fields,
    "session_id": session_id_header,
    "payment_channel_id": None,
    "agent_id": agent_id_header,
    "agent_type": agent_type_header,
    "agent_vendor": agent_vendor_header,
    "agent_version": agent_version_header,
    "request_purpose": request_purpose_header,
}


# 🔵 UPDATE NORMAL FLOW ECON (final block)

# FIND THIS BLOCK near the end:
# econ = { ... }

# REPLACE WITH:

payment_status = decision.econ_payment_status

if decision.econ_payment_required and payment_method_header == "mpp":
    if validation_valid:
        payment_status = "presented"
    else:
        payment_status = "would_block_under_402" if not should_enforce_agent_pay else "failed_validation"

econ_payment_fields = build_econ_payment_fields(
    payment_required=decision.econ_payment_required,
    payment_status=payment_status,
    payment_method_header=payment_method_header,
    payment_network_header=payment_network_header,
    payment_token_header=payment_token_header,
    payment_amount_header=payment_amount_header,
    payment_reference_header=payment_reference_header,
    decision=decision,
)

econ = {
    "request_id": request_id,
    "customer_id": getattr(request.state, "customer_id", None),
    "api_key_id": getattr(request.state, "api_key_id", None),
    "pricing_rule_id": economic_rule_name,
    "unit_price_usd": unit_price_usd,
    "billed_amount_usd": billed_amount_usd,
    "payment_required": decision.econ_payment_required,
    **econ_payment_fields,
    "session_id": session_id_header,
    "payment_channel_id": None,
    "agent_id": agent_id_header,
    "agent_type": agent_type_header,
    "agent_vendor": agent_vendor_header,
    "agent_version": agent_version_header,
    "request_purpose": request_purpose_header,
}