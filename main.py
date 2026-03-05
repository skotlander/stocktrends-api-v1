# main.py
from fastapi import FastAPI
from middleware.request_id import RequestIdMiddleware

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


# (you'll add more routers soon)

app = FastAPI(title="Stock Trends API", version="1.0.0")

app.add_middleware(RequestIdMiddleware)

# Versioned API
v1 = FastAPI(title="Stock Trends API v1", version="1.0.0")
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

app.mount("/v1", v1)

@app.get("/health")
def health():
    return {"status": "ok"}