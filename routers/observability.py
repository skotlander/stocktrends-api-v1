from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from db import get_metering_engine

router = APIRouter(prefix="/observability", tags=["observability"])

_RECENT_REQUESTS_LIMIT = 10


def _require_auth(request: Request) -> None:
    """
    Ensure the request is authenticated via a subscription API key.

    MPP rows in api_request_economics carry customer_id = NULL because the
    agent-pay authentication path (api_key.py _apply_agent_pay_context) sets
    request.state.customer_id = None for all MPP traffic.  The observability
    endpoint is called by a human operator with a subscription API key —
    customer_id IS set on the observability request itself — but it must NOT
    be used to filter the metering query because the target MPP rows belong to
    an anonymous (keyless) agent whose customer_id is always NULL.
    """
    customer_id = getattr(request.state, "customer_id", None)
    if not customer_id:
        raise HTTPException(status_code=401, detail="Authenticated customer context required")


@router.get(
    "/mpp/sessions/{payment_channel_id}",
    summary="MPP session summary",
    description=(
        "Returns an aggregated summary of all MPP-rail requests recorded for a payment channel. "
        "payment_channel_id is the canonical MPP session key (X-StockTrends-Payment-Channel-Id "
        "header, used as channel_id in both authorize and capture control-plane calls). "
        "Rows are scoped to payment_rail='mpp' only — x402 and subscription records are excluded. "
        "Note: MPP rows carry customer_id=NULL in metering; scoping is by payment_channel_id alone. "
        "Requires a valid subscription API key. Returns 404 if no MPP records exist for the channel."
    ),
)
def get_mpp_session(payment_channel_id: str, request: Request):
    _require_auth(request)

    # MPP rows have customer_id=NULL (set by _apply_agent_pay_context in the auth middleware).
    # Do not filter by customer_id — scope only by payment_channel_id + payment_rail.
    params = {"payment_channel_id": payment_channel_id}

    engine = get_metering_engine()
    with engine.begin() as conn:
        summary_row = conn.execute(
            text("""
                SELECT
                    COUNT(*) AS request_count,
                    MAX(session_id) AS session_id,
                    MIN(created_at) AS first_seen_at,
                    MAX(created_at) AS last_seen_at,
                    SUM(COALESCE(stc_cost, 0)) AS total_stc_requested,
                    SUM(
                        CASE WHEN payment_status = 'captured'
                             THEN COALESCE(stc_cost, 0) ELSE 0 END
                    ) AS total_stc_captured,
                    SUM(
                        CASE WHEN payment_status = 'captured'
                             THEN COALESCE(billed_amount_usd, 0) ELSE 0 END
                    ) AS total_billed_usd_captured
                FROM api_request_economics
                WHERE payment_channel_id = :payment_channel_id
                  AND payment_rail = 'mpp'
            """),
            params,
        ).mappings().first()

        if not summary_row or int(summary_row.get("request_count") or 0) == 0:
            raise HTTPException(status_code=404, detail="MPP session not found")

        status_rows = conn.execute(
            text("""
                SELECT
                    payment_status,
                    COUNT(*) AS request_count
                FROM api_request_economics
                WHERE payment_channel_id = :payment_channel_id
                  AND payment_rail = 'mpp'
                GROUP BY payment_status
                ORDER BY request_count DESC, payment_status
            """),
            params,
        ).mappings().all()

        recent_rows = conn.execute(
            text("""
                SELECT
                    request_id,
                    payment_status,
                    payment_reference,
                    stc_cost,
                    billed_amount_usd,
                    pricing_rule_id,
                    created_at
                FROM api_request_economics
                WHERE payment_channel_id = :payment_channel_id
                  AND payment_rail = 'mpp'
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {**params, "limit": _RECENT_REQUESTS_LIMIT},
        ).mappings().all()

    summary = dict(summary_row)
    return {
        "request_id": getattr(request.state, "request_id", None),
        "payment_channel_id": payment_channel_id,
        "session_id": summary.get("session_id"),
        "request_count": int(summary.get("request_count") or 0),
        "first_seen_at": summary["first_seen_at"].isoformat() if summary.get("first_seen_at") else None,
        "last_seen_at": summary["last_seen_at"].isoformat() if summary.get("last_seen_at") else None,
        # total_stc_requested: STC value of all requests in this session (informational).
        # Includes authorized, capture_failed, and presented rows — not all resulted in
        # real deductions from the session balance.
        "total_stc_requested": float(summary.get("total_stc_requested") or 0),
        # total_stc_captured / total_billed_usd_captured: actual deductions from the session
        # balance.  Only rows with payment_status='captured' represent settled charges.
        "total_stc_captured": float(summary.get("total_stc_captured") or 0),
        "total_billed_usd_captured": float(summary.get("total_billed_usd_captured") or 0),
        "payment_status_breakdown": [
            {
                "payment_status": row.get("payment_status"),
                "request_count": int(row.get("request_count") or 0),
            }
            for row in status_rows
        ],
        "recent_requests": [
            {
                "request_id": row.get("request_id"),
                "payment_status": row.get("payment_status"),
                "payment_reference": row.get("payment_reference"),
                "stc_cost": float(row["stc_cost"]) if row.get("stc_cost") is not None else None,
                "billed_amount_usd": float(row["billed_amount_usd"]) if row.get("billed_amount_usd") is not None else None,
                "pricing_rule_id": row.get("pricing_rule_id"),
                "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
            }
            for row in recent_rows
        ],
    }
