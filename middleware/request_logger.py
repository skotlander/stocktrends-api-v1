import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("stocktrends_api.requests")


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        ms = int((time.time() - start) * 1000)

        request_id = getattr(request.state, "request_id", None)
        api_key_id = getattr(request.state, "api_key_id", None)

        logger.info(
            "request_id=%s method=%s path=%s status=%s ms=%s api_key=%s ip=%s ua=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            ms,
            api_key_id,
            request.client.host if request.client else None,
            request.headers.get("user-agent"),
        )
        return response
