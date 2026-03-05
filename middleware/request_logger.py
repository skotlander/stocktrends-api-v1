import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("stocktrends_api.requests")


def detect_ai_agent(user_agent: str) -> str | None:
    if not user_agent:
        return None

    ua = user_agent.lower()

    if "gptbot" in ua:
        return "OpenAI GPTBot"
    if "openai-user" in ua:
        return "OpenAI Tool User"
    if "claudebot" in ua:
        return "Anthropic Claude"
    if "perplexitybot" in ua:
        return "Perplexity AI"
    if "google-extended" in ua:
        return "Google AI"
    if "bytespider" in ua:
        return "ByteDance AI"
    if "ccbot" in ua:
        return "Common Crawl"

    return None


class RequestLoggerMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        start = time.time()
        response = await call_next(request)
        ms = int((time.time() - start) * 1000)

        request_id = getattr(request.state, "request_id", None)
        api_key_id = getattr(request.state, "api_key_id", None)

        user_agent = request.headers.get("user-agent", "")
        ai_agent = detect_ai_agent(user_agent)

        logger.info(
            "request_id=%s method=%s path=%s status=%s ms=%s api_key=%s ai_agent=%s ip=%s ua=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            ms,
            api_key_id,
            ai_agent,
            request.client.host if request.client else None,
            user_agent,
        )

        return response