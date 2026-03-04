# middleware/request_id.py
from __future__ import annotations
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-Id"

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = rid
        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response