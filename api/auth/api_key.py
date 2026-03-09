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
                        id,
                        customer_id,
                        plan_code,
                        active
                    FROM api_keys
                    WHERE api_key_hash = :api_key_hash
                    LIMIT 1
                """),
                {"api_key_hash": token_hash},
            ).mappings().first()

            if row:
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

    if not row["active"]:
        raise HTTPException(status_code=403, detail="API key inactive")

    return {
        "api_key_id": row["id"],
        "customer_id": row["customer_id"],
        "plan_code": row["plan_code"],
    }