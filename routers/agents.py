from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from db import get_metering_engine

router = APIRouter(prefix="/agents", tags=["agents"])


def _require_customer_id(request: Request) -> str:
    customer_id = getattr(request.state, "customer_id", None)
    if not customer_id:
        raise HTTPException(status_code=401, detail="Authenticated customer context required")
    return customer_id


def _parse_since_days(days: int) -> datetime:
    safe_days = max(1, min(days, 365))
    return datetime.now(timezone.utc) - timedelta(days=safe_days)


def _serialize_agent_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": row.get("id"),
        "customer_id": row.get("customer_id"),
        "agent_identifier": row.get("agent_identifier"),
        "agent_type": row.get("agent_type"),
        "agent_vendor": row.get("agent_vendor"),
        "display_name": row.get("display_name"),
        "status": row.get("status"),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
        "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
    }


def _get_agent_for_customer(customer_id: str, agent_id: str) -> dict[str, Any]:
    engine = get_metering_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    id,
                    customer_id,
                    agent_identifier,
                    agent_type,
                    agent_vendor,
                    display_name,
                    status,
                    created_at,
                    updated_at
                FROM api_agents
                WHERE id = :agent_id
                  AND customer_id = :customer_id
                LIMIT 1
                """
            ),
            {
                "agent_id": agent_id,
                "customer_id": customer_id,
            },
        ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return dict(row)


@router.get(
    "",
    summary="List agents for the authenticated customer",
    description=(
        "Returns agents registered under the authenticated customer account. "
        "This is the primary Lane B management surface for viewing agent identity and status."
    ),
)
def list_agents(
    request: Request,
    status: str | None = Query(default=None, description="Optional status filter, e.g. active or disabled"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    customer_id = _require_customer_id(request)

    where_sql = "WHERE customer_id = :customer_id"
    params: dict[str, Any] = {
        "customer_id": customer_id,
        "limit": limit,
        "offset": offset,
    }

    if status:
        where_sql += " AND status = :status"
        params["status"] = status.strip().lower()

    sql = text(
        f"""
        SELECT
            id,
            customer_id,
            agent_identifier,
            agent_type,
            agent_vendor,
            display_name,
            status,
            created_at,
            updated_at
        FROM api_agents
        {where_sql}
        ORDER BY updated_at DESC, created_at DESC, id DESC
        LIMIT :limit OFFSET :offset
        """
    )

    count_sql = text(
        f"""
        SELECT COUNT(*) AS total
        FROM api_agents
        {where_sql}
        """
    )

    engine = get_metering_engine()
    with engine.begin() as conn:
        rows = conn.execute(sql, params).mappings().all()
        total = conn.execute(count_sql, params).scalar() or 0

    items = [_serialize_agent_row(dict(row)) for row in rows]

    return {
        "request_id": getattr(request.state, "request_id", None),
        "customer_id": customer_id,
        "count": len(items),
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get(
    "/{agent_id}",
    summary="Get agent detail",
    description="Returns a single registered agent for the authenticated customer.",
)
def get_agent_detail(agent_id: str, request: Request):
    customer_id = _require_customer_id(request)
    agent = _get_agent_for_customer(customer_id, agent_id)

    engine = get_metering_engine()
    with engine.begin() as conn:
        usage_row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS request_count,
                    MIN(event_time_utc) AS first_seen_at,
                    MAX(event_time_utc) AS last_seen_at,
                    SUM(CASE WHEN status_code >= 200 AND status_code < 400 THEN 1 ELSE 0 END) AS success_count,
                    SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS error_count
                FROM api_request_logs
                WHERE customer_id = :customer_id
                  AND agent_id = :agent_id
                """
            ),
            {
                "customer_id": customer_id,
                "agent_id": agent_id,
            },
        ).mappings().first()

        pricing_rows = conn.execute(
            text(
                """
                SELECT
                    pricing_rule_id,
                    COUNT(*) AS request_count
                FROM api_request_logs
                WHERE customer_id = :customer_id
                  AND agent_id = :agent_id
                GROUP BY pricing_rule_id
                ORDER BY request_count DESC, pricing_rule_id
                """
            ),
            {
                "customer_id": customer_id,
                "agent_id": agent_id,
            },
        ).mappings().all()

    usage = dict(usage_row) if usage_row else {}
    usage_summary = {
        "request_count": int(usage.get("request_count") or 0),
        "first_seen_at": usage.get("first_seen_at").isoformat() if usage.get("first_seen_at") else None,
        "last_seen_at": usage.get("last_seen_at").isoformat() if usage.get("last_seen_at") else None,
        "success_count": int(usage.get("success_count") or 0),
        "error_count": int(usage.get("error_count") or 0),
    }

    pricing_breakdown = [
        {
            "pricing_rule_id": row.get("pricing_rule_id"),
            "request_count": int(row.get("request_count") or 0),
        }
        for row in pricing_rows
    ]

    return {
        "request_id": getattr(request.state, "request_id", None),
        "agent": _serialize_agent_row(agent),
        "usage_summary": usage_summary,
        "pricing_breakdown": pricing_breakdown,
    }


@router.get(
    "/{agent_id}/usage",
    summary="Get agent usage summary",
    description=(
        "Returns usage, pricing, and economics summaries for a single registered agent. "
        "The window is controlled by `days`."
    ),
)
def get_agent_usage(
    agent_id: str,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
):
    customer_id = _require_customer_id(request)
    agent = _get_agent_for_customer(customer_id, agent_id)
    since_dt = _parse_since_days(days)

    engine = get_metering_engine()
    with engine.begin() as conn:
        request_summary = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS request_count,
                    SUM(CASE WHEN status_code >= 200 AND status_code < 400 THEN 1 ELSE 0 END) AS success_count,
                    SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS error_count,
                    AVG(latency_ms) AS avg_latency_ms,
                    MAX(event_time_utc) AS last_seen_at
                FROM api_request_logs
                WHERE customer_id = :customer_id
                  AND agent_id = :agent_id
                  AND event_time_utc >= :since_dt
                """
            ),
            {
                "customer_id": customer_id,
                "agent_id": agent_id,
                "since_dt": since_dt,
            },
        ).mappings().first()

        endpoint_rows = conn.execute(
            text(
                """
                SELECT
                    endpoint_path,
                    COUNT(*) AS request_count
                FROM api_request_logs
                WHERE customer_id = :customer_id
                  AND agent_id = :agent_id
                  AND event_time_utc >= :since_dt
                GROUP BY endpoint_path
                ORDER BY request_count DESC, endpoint_path
                LIMIT 25
                """
            ),
            {
                "customer_id": customer_id,
                "agent_id": agent_id,
                "since_dt": since_dt,
            },
        ).mappings().all()

        daily_rows = conn.execute(
            text(
                """
                SELECT
                    DATE(event_time_utc) AS usage_date,
                    COUNT(*) AS request_count
                FROM api_request_logs
                WHERE customer_id = :customer_id
                  AND agent_id = :agent_id
                  AND event_time_utc >= :since_dt
                GROUP BY DATE(event_time_utc)
                ORDER BY usage_date DESC
                """
            ),
            {
                "customer_id": customer_id,
                "agent_id": agent_id,
                "since_dt": since_dt,
            },
        ).mappings().all()

        economics_row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS economics_rows,
                    SUM(COALESCE(billed_amount_usd, 0)) AS total_billed_amount_usd,
                    SUM(COALESCE(payment_amount_usd, 0)) AS total_payment_amount_usd
                FROM api_request_economics
                WHERE customer_id = :customer_id
                  AND agent_id = :agent_id
                  AND created_at >= :since_dt
                """
            ),
            {
                "customer_id": customer_id,
                "agent_id": agent_id,
                "since_dt": since_dt,
            },
        ).mappings().first()

        payment_rows = conn.execute(
            text(
                """
                SELECT
                    payment_status,
                    payment_method,
                    COUNT(*) AS request_count
                FROM api_request_economics
                WHERE customer_id = :customer_id
                  AND agent_id = :agent_id
                  AND created_at >= :since_dt
                GROUP BY payment_status, payment_method
                ORDER BY request_count DESC, payment_status, payment_method
                """
            ),
            {
                "customer_id": customer_id,
                "agent_id": agent_id,
                "since_dt": since_dt,
            },
        ).mappings().all()

    req = dict(request_summary) if request_summary else {}
    econ = dict(economics_row) if economics_row else {}

    return {
        "request_id": getattr(request.state, "request_id", None),
        "agent": _serialize_agent_row(agent),
        "window": {
            "days": days,
            "since_utc": since_dt.isoformat(),
        },
        "request_summary": {
            "request_count": int(req.get("request_count") or 0),
            "success_count": int(req.get("success_count") or 0),
            "error_count": int(req.get("error_count") or 0),
            "avg_latency_ms": float(req.get("avg_latency_ms") or 0),
            "last_seen_at": req.get("last_seen_at").isoformat() if req.get("last_seen_at") else None,
        },
        "economics_summary": {
            "economics_rows": int(econ.get("economics_rows") or 0),
            "total_billed_amount_usd": float(econ.get("total_billed_amount_usd") or 0),
            "total_payment_amount_usd": float(econ.get("total_payment_amount_usd") or 0),
        },
        "top_endpoints": [
            {
                "endpoint_path": row.get("endpoint_path"),
                "request_count": int(row.get("request_count") or 0),
            }
            for row in endpoint_rows
        ],
        "daily_usage": [
            {
                "usage_date": row.get("usage_date").isoformat() if isinstance(row.get("usage_date"), date) else str(row.get("usage_date")),
                "request_count": int(row.get("request_count") or 0),
            }
            for row in daily_rows
        ],
        "payment_breakdown": [
            {
                "payment_status": row.get("payment_status"),
                "payment_method": row.get("payment_method"),
                "request_count": int(row.get("request_count") or 0),
            }
            for row in payment_rows
        ],
    }


@router.post(
    "/{agent_id}/disable",
    summary="Disable agent",
    description="Disables a registered agent for the authenticated customer.",
)
def disable_agent(agent_id: str, request: Request):
    customer_id = _require_customer_id(request)
    _get_agent_for_customer(customer_id, agent_id)

    engine = get_metering_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE api_agents
                SET status = 'disabled',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :agent_id
                  AND customer_id = :customer_id
                """
            ),
            {
                "agent_id": agent_id,
                "customer_id": customer_id,
            },
        )

    agent = _get_agent_for_customer(customer_id, agent_id)

    return {
        "request_id": getattr(request.state, "request_id", None),
        "ok": True,
        "action": "disabled",
        "agent": _serialize_agent_row(agent),
    }


@router.post(
    "/{agent_id}/enable",
    summary="Enable agent",
    description="Re-enables a registered agent for the authenticated customer.",
)
def enable_agent(agent_id: str, request: Request):
    customer_id = _require_customer_id(request)
    _get_agent_for_customer(customer_id, agent_id)

    engine = get_metering_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE api_agents
                SET status = 'active',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :agent_id
                  AND customer_id = :customer_id
                """
            ),
            {
                "agent_id": agent_id,
                "customer_id": customer_id,
            },
        )

    agent = _get_agent_for_customer(customer_id, agent_id)

    return {
        "request_id": getattr(request.state, "request_id", None),
        "ok": True,
        "action": "enabled",
        "agent": _serialize_agent_row(agent),
    }