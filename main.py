# main.py
import logging

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse

from middleware.request_id import RequestIdMiddleware
from middleware.api_key import ApiKeyMiddleware
from middleware.request_logger import RequestLoggerMiddleware
from middleware.metering import MeteringMiddleware

from routers.instruments import router as instruments_router
from routers.prices import router as prices_router
from routers.indicators import router as indicators_router
from routers.selections import router as selections_router
from routers.stim import router as stim_router
from routers.selections_published import router as selections_published_router
from routers.stwr import router as stwr_router
from routers.meta import router as meta_router
from routers.breadth import router as breadth_router
from routers.leadership import router as leadership_router
from routers.ai import router as ai_router
from routers.pricing import router as pricing_router

logging.basicConfig(level=logging.INFO)

APP_TITLE = "Stock Trends API"
APP_VERSION = "1.0.0"

FREE_METERED_V1_PATHS = {
    "/ai/context",
    "/breadth/sector/latest",
}


def is_protected_v1_path(path: str) -> bool:
    """
    In the live middleware, most /v1/* paths are protected except:
    - public/static/docs/openapi paths
    - specific free-metered endpoints

    Since this schema is for the mounted /v1 app, its paths do not include
    the /v1 prefix. So we only need to exempt the known free-metered routes.
    """
    return path not in FREE_METERED_V1_PATHS


def apply_api_key_security_to_openapi(v1_app: FastAPI) -> dict:
    if v1_app.openapi_schema:
        return v1_app.openapi_schema

    openapi_schema = get_openapi(
        title=f"{APP_TITLE} v1",
        version=APP_VERSION,
        description=(
            "Stock Trends API v1.\n\n"
            "Most `/v1/*` endpoints require authentication.\n\n"
            "Use the **Authorize** button and provide either:\n"
            "- `X-API-Key` header, or\n"
            "- `Authorization: Bearer <API_KEY>`\n\n"
            "Public / free-metered endpoints remain callable without a key.\n\n"
            "Pricing discovery:\n"
            "- `GET /v1/pricing` returns machine-readable pricing metadata.\n"
            "- Some endpoints, especially `/v1/stim/*`, may support agent payment metadata.\n\n"
            "Supported agent headers:\n"
            "- `X-StockTrends-Agent-Id`\n"
            "- `X-StockTrends-Agent-Type`\n"
            "- `X-StockTrends-Agent-Vendor`\n"
            "- `X-StockTrends-Agent-Version`\n"
            "- `X-StockTrends-Request-Purpose`\n"
            "- `X-StockTrends-Session-Id`\n\n"
            "Supported payment headers:\n"
            "- `X-StockTrends-Payment-Method`\n"
            "- `X-StockTrends-Payment-Network`\n"
            "- `X-StockTrends-Payment-Token`\n"
            "- `X-StockTrends-Payment-Reference`\n"
            "- `X-StockTrends-Payment-Amount`\n"
            "- `X-StockTrends-Pricing-Rule`\n\n"
            "Pricing discovery response headers may include:\n"
            "- `X-StockTrends-Pricing-Rule`\n"
            "- `X-StockTrends-Payment-Required`\n"
            "- `X-StockTrends-Accepted-Payment-Methods`\n"
        ),
        routes=v1_app.routes,
    )

    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})

    security_schemes["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Paste your Stock Trends API key. It will be sent as the `X-API-Key` header.",
    }

    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "API Key",
        "description": "Alternative format: `Authorization: Bearer <API_KEY>`",
    }

    for path, path_item in openapi_schema.get("paths", {}).items():
        protected = is_protected_v1_path(path)

        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue

            if protected:
                operation["security"] = [
                    {"ApiKeyAuth": []},
                    {"BearerAuth": []},
                ]
            else:
                operation["security"] = []

    v1_app.openapi_schema = openapi_schema
    return v1_app.openapi_schema


app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
)


@app.get("/llms.txt", include_in_schema=False)
def llms_txt():
    return FileResponse("static/llms.txt", media_type="text/plain")


# Middleware order matters
app.add_middleware(RequestIdMiddleware)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(MeteringMiddleware)
app.add_middleware(RequestLoggerMiddleware)

# Versioned API sub-application
v1 = FastAPI(
    title=f"{APP_TITLE} v1",
    version=APP_VERSION,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

v1.include_router(instruments_router)
v1.include_router(prices_router)
v1.include_router(indicators_router)
v1.include_router(selections_router)
v1.include_router(stim_router)
v1.include_router(selections_published_router)
v1.include_router(stwr_router)
v1.include_router(meta_router)
v1.include_router(breadth_router)
v1.include_router(leadership_router)
v1.include_router(ai_router)
v1.include_router(pricing_router)

v1.openapi = lambda: apply_api_key_security_to_openapi(v1)

app.mount("/v1", v1)


@app.get("/health")
def health():
    return {"ok": True}