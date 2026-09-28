import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propagates request_id / correlation_id across all incoming requests and outgoing responses."""
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or f"req_{uuid.uuid4().hex[:12]}"
        )
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

