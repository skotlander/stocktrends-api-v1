import time
from datetime import datetime
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from db import get_engine
from pricing.classifier import classify_request


class MeteringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):

        start_time = time.time()

        # request_id should already exist from RequestIdMiddleware
        request_id = getattr(request.state, "request_id", None)

        response: Response = await call_next(request)

        latency_ms = int((time.time() - start_time) * 1000)

        # --------------------------------------------------
        # SAFE CONTEXT EXTRACTION (never fail)
        # --------------------------------------------------
        try:
            auth_mode = getattr(request.state, "auth_mode", "unknown")
            api_key_id = getattr(request.state, "api_key_id", None)
            customer_id = getattr(request.state, "customer_id", None)
            subscription_id = getattr(request.state, "subscription_id", None)
            plan_code = getattr(request.state, "plan_code", None)

            # ✅ SAFE ENUM MAPPING (fixes your schema issue permanently)
            if auth_mode in ("api_key", "free_metered"):
                workflow_type = "human"
            elif auth_mode == "agent":
                workflow_type = "agent"
            else:
                workflow_type = "unknown"

            path = request.url.path
            method = request.method
            query_string = str(request.url.query)

            symbol = request.query_params.get("symbol")
            exchange = request.query_params.get("exchange")
            symbol_exchange = request.query_params.get("symbol_exchange")

            client_ip = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
            referer = request.headers.get("referer")

            status_code = response.status_code
            success = 1 if status_code < 400 else 0

            response_size = None
            if hasattr(response, "body") and response.body:
                response_size = len(response.body)

        except Exception as e:
            print(f"[METERING ERROR] context extraction failed: {e}")
            return response  # never break request flow

        # --------------------------------------------------
        # PRICING CLASSIFICATION (always runs)
        # --------------------------------------------------
        try:
            classification = classify_request(
                path=path,
                method=method,
                auth_mode=auth_mode,
                plan_code=plan_code
            )

            pricing_rule_id = classification.get("pricing_rule_id", "default_subscription")
            payment_required = classification.get("payment_required", False)
            payment_method = classification.get("payment_method", "subscription")

        except Exception as e:
            print(f"[METERING ERROR] classification failed: {e}")
            pricing_rule_id = "default_subscription"
            payment_required = False
            payment_method = "subscription"

        # --------------------------------------------------
        # DATABASE INSERTS (decoupled + safe)
        # --------------------------------------------------
        try:
            engine = get_engine()

            with engine.begin() as conn:

                # --------------------------
                # REQUEST LOG
                # --------------------------
                conn.execute(
                    """
                    INSERT INTO api_request_logs (
                        event_time_utc,
                        request_id,
                        environment,
                        api_key_id,
                        customer_id,
                        subscription_id,
                        plan_code,
                        actor_type,
                        workflow_type,
                        agent_identifier,
                        endpoint_path,
                        route_template,
                        endpoint_family,
                        http_method,
                        query_string,
                        symbol,
                        exchange,
                        symbol_exchange,
                        status_code,
                        success,
                        latency_ms,
                        response_size_bytes,
                        client_ip,
                        user_agent,
                        referer,
                        is_metered,
                        is_billable,
                        payment_method,
                        pricing_rule_id
                    ) VALUES (
                        :event_time_utc,
                        :request_id,
                        'production',
                        :api_key_id,
                        :customer_id,
                        :subscription_id,
                        :plan_code,
                        'external_customer',
                        :workflow_type,
                        NULL,
                        :endpoint_path,
                        NULL,
                        NULL,
                        :http_method,
                        :query_string,
                        :symbol,
                        :exchange,
                        :symbol_exchange,
                        :status_code,
                        :success,
                        :latency_ms,
                        :response_size_bytes,
                        :client_ip,
                        :user_agent,
                        :referer,
                        1,
                        :is_billable,
                        :payment_method,
                        :pricing_rule_id
                    )
                    """,
                    {
                        "event_time_utc": datetime.utcnow(),
                        "request_id": request_id,
                        "api_key_id": api_key_id,
                        "customer_id": customer_id,
                        "subscription_id": subscription_id,
                        "plan_code": plan_code,
                        "workflow_type": workflow_type,
                        "endpoint_path": path,
                        "http_method": method,
                        "query_string": query_string,
                        "symbol": symbol,
                        "exchange": exchange,
                        "symbol_exchange": symbol_exchange,
                        "status_code": status_code,
                        "success": success,
                        "latency_ms": latency_ms,
                        "response_size_bytes": response_size,
                        "client_ip": client_ip,
                        "user_agent": user_agent,
                        "referer": referer,
                        "is_billable": 1 if payment_required else 0,
                        "payment_method": payment_method,
                        "pricing_rule_id": pricing_rule_id,
                    },
                )

                # --------------------------
                # ECONOMICS (only if parent exists)
                # --------------------------
                try:
                    conn.execute(
                        """
                        INSERT INTO api_request_economics (
                            request_id,
                            pricing_rule_id,
                            payment_required,
                            payment_status,
                            payment_method,
                            created_at
                        ) VALUES (
                            :request_id,
                            :pricing_rule_id,
                            :payment_required,
                            'not_required',
                            :payment_method,
                            NOW()
                        )
                        """,
                        {
                            "request_id": request_id,
                            "pricing_rule_id": pricing_rule_id,
                            "payment_required": 1 if payment_required else 0,
                            "payment_method": payment_method,
                        },
                    )
                except Exception as econ_err:
                    print(f"[METERING WARNING] economics insert failed: {econ_err}")

        except Exception as db_err:
            print(f"[METERING ERROR] request-log insert failed: {db_err}")

        # --------------------------------------------------
        # RESPONSE HEADERS (always applied)
        # --------------------------------------------------
        response.headers["x-request-id"] = request_id or ""
        response.headers["x-stocktrends-pricing-rule"] = pricing_rule_id
        response.headers["x-stocktrends-payment-required"] = str(payment_required).lower()
        response.headers["x-stocktrends-accepted-payment-methods"] = "subscription,mpp,x402,crypto"

        return response