from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects OWASP enterprise security headers and masks server technology fingerprints."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 1. Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 2. Prevent Clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # 3. Enable legacy XSS filter protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # 4. Strict Transport Security (HSTS)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # 5. Restrict Referrer Info
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 6. Restrict Browser Features & Permissions
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(self), geolocation=(), payment=()"
        )

        # 7. Cloak / Disguise Server Header (Hides uvicorn / python fingerprint)
        response.headers["Server"] = "Fortress-Shield/2.0"

        return response

