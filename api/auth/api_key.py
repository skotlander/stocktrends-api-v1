import hashlib

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from db import get_auth_engine

security = HTTPBearer()


def get_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    if not token:
        raise HTTPException(status_code=401, detail="Invalid API key")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    engine = get_auth_engine()

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT
                        k.id,
                        k.customer_id,
                        k.status,
                        s.status AS subscription_status,
                        p.code AS plan_code
                    FROM api_keys k
                    LEFT JOIN api_subscriptions s
                        ON k.subscription_id = s.id
                    LEFT JOIN api_plans p
                        ON s.plan_id = p.id
                    WHERE k.key_hash = :key_hash
                    LIMIT 1
                """),
                {"key_hash": token_hash},
            ).mappings().first()

            if row:
                # update last_used_at
                conn.execute(
                    text("""
                        UPDATE api_keys
                        SET last_used_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {"id": row["id"]},
                )
                conn.commit()

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Auth database error: {str(e)}",
        )

    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="API key revoked")

    if row["subscription_status"] not in ("active", "trialing"):
        raise HTTPException(status_code=403, detail="Subscription inactive")

    return {
        "api_key_id": row["id"],
        "customer_id": row["customer_id"],
        "plan_code": row["plan_code"],
    }