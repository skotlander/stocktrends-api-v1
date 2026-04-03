from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from payments.x402 import (
    build_x402_challenge,
    build_x402_requirements,
    has_payment_signature,
    settle_with_facilitator,
    verify_with_facilitator,
)


def _extract_x402_requirement_context(payment_requirements: dict) -> tuple[str | None, str | None]:
    accepts = payment_requirements.get("accepts")
    if not isinstance(accepts, list) or not accepts or not isinstance(accepts[0], dict):
        return None, None

    requirement = accepts[0]
    network = requirement.get("network")
    token = requirement.get("asset")

    return network, token


@dataclass
class PaymentEnforcementResult:
    outcome: str
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    challenge_body: Optional[dict] = None
    payment_required_header: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_network: Optional[str] = None
    payment_token: Optional[str] = None
    payment_amount_native: Optional[Decimal] = None
    payment_channel_id: Optional[str] = None
    payment_response: Optional[dict] = None


def enforce_x402_payment(
    *,
    headers,
    path: str,
    method: str,
    amount_usd: Decimal,
    validation_valid: bool,
    validation_error: str | None,
    validation_detail: str | None,
    validated_payment_reference: str | None,
    validated_payment_network: str | None,
    validated_payment_token: str | None,
    validated_payment_amount_native: Decimal | None,
    replay_checker: Callable[[str], bool],
) -> PaymentEnforcementResult:
    current_payment_requirements = build_x402_requirements(
        path=path,
        amount_usd=amount_usd,
        method=method,
    )
    required_network, required_token = _extract_x402_requirement_context(current_payment_requirements)

    if not has_payment_signature(headers):
        challenge_body, payment_required_header = build_x402_challenge(
            path=path,
            amount_usd=amount_usd,
            method=method,
        )
        return PaymentEnforcementResult(
            outcome="challenge",
            error_code="payment_required",
            error_detail="x402 payment required",
            challenge_body=challenge_body,
            payment_required_header=payment_required_header,
            payment_network=required_network,
            payment_token=required_token,
        )

    if not validation_valid:
        return PaymentEnforcementResult(
            outcome="validation_failed",
            error_code=validation_error,
            error_detail=validation_detail,
            payment_reference=validated_payment_reference,
            payment_network=validated_payment_network or required_network,
            payment_token=validated_payment_token or required_token,
            payment_amount_native=validated_payment_amount_native,
        )

    replay_reference = validated_payment_reference
    if replay_reference and replay_checker(replay_reference):
        return PaymentEnforcementResult(
            outcome="replay_detected",
            error_code="replay_detected",
            error_detail="Payment reference has already been used.",
            payment_reference=replay_reference,
            payment_network=validated_payment_network or required_network,
            payment_token=validated_payment_token or required_token,
            payment_amount_native=validated_payment_amount_native,
        )

    payment_signature = headers.get("payment-signature") or headers.get("x-payment")

    verify_result = verify_with_facilitator(
        payment_signature=payment_signature,
        payment_requirements=current_payment_requirements,
    )
    if not verify_result.valid:
        return PaymentEnforcementResult(
            outcome="verification_failed",
            error_code="payment_verification_failed",
            error_detail=verify_result.error_detail,
            payment_reference=replay_reference,
            payment_network=validated_payment_network or required_network,
            payment_token=validated_payment_token or required_token,
            payment_amount_native=validated_payment_amount_native,
        )

    settle_result = settle_with_facilitator(
        payment_signature=payment_signature,
        payment_requirements=current_payment_requirements,
    )
    if not settle_result.valid:
        return PaymentEnforcementResult(
            outcome="settlement_failed",
            error_code="payment_settlement_failed",
            error_detail=settle_result.error_detail,
            payment_reference=replay_reference,
            payment_network=validated_payment_network or required_network,
            payment_token=validated_payment_token or required_token,
            payment_amount_native=validated_payment_amount_native,
        )

    return PaymentEnforcementResult(
        outcome="proceed",
        payment_reference=replay_reference,
        payment_network=validated_payment_network or required_network,
        payment_token=validated_payment_token or required_token,
        payment_amount_native=validated_payment_amount_native,
        payment_response=settle_result.settlement_response,
    )


def enforce_mpp_payment_stub(**_kwargs) -> PaymentEnforcementResult:
    return PaymentEnforcementResult(outcome="not_implemented")


def enforce_payment_rail(
    *,
    payment_rail: str,
    **kwargs,
) -> PaymentEnforcementResult:
    if payment_rail == "x402":
        return enforce_x402_payment(**kwargs)

    if payment_rail == "mpp":
        return enforce_mpp_payment_stub(**kwargs)

    return PaymentEnforcementResult(outcome="not_applicable")
