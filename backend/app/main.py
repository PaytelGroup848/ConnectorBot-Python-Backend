from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from app.core.config import settings
from app.core.redis import cache_service
from app.core.exceptions import (
    APIException,
    api_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
)
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.security_jail import SecurityJailMiddleware
from app.middleware.waf_shield import WAFShieldMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
import app.models

# Import Domain Microservices Routers
from app.modules.system.router import router as system_router
from app.modules.system.honeypot import router as honeypot_router
from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.conversations.router import router as conversations_router
from app.modules.knowledge.router import router as knowledge_router
from app.modules.tickets.router import router as tickets_router
from app.modules.admin.router import router as admin_router
from app.modules.usage.router import router as usage_router
from app.modules.voice.router import router as voice_router
from app.modules.connector.router import router as connector_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize cache & resilient connections
    await cache_service.init()
    yield
    # Shutdown logic if needed


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="1.0.0",
        description="Production Multi-Tenant AI Assistant for Connector & Tally SaaS",
        lifespan=lifespan,
    )

    # 1. Active WAF Shield (Deep Packet Inspection for SQLi, XSS, RCE, Path Traversal, Prompt Hijack)
    app.add_middleware(WAFShieldMiddleware)

    # 2. Security Jail & Hostile IP Auto-Ban Middleware (Drops banned IPs immediately)
    app.add_middleware(SecurityJailMiddleware)

    # 3. Correlation ID Middleware (Section 54)
    app.add_middleware(CorrelationIdMiddleware)

    # 4. OWASP Enterprise Security Headers & Stealth Cloaking Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 5. CORS Middleware (Explicit whitelist, avoiding '*' for secure auth - Section 120)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://connector.cloudata.in",
            "http://connector.cloudata.in",
            "https://ctrlbooks.com",
            "https://www.ctrlbooks.com",
            "https://app.ctrlbooks.com",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://210.56.147.234:3000",
            "http://210.56.147.234:8001",
            "http://210.56.147.234",
        ],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|210\.56\.147\.234)(:\d+)?",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )

    # 4. Centralized Exception Handlers (Section 12 & 53)
    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # 5. Mount Decoy Honeypots & Domain Microservices
    app.include_router(honeypot_router)
    app.include_router(system_router)
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(conversations_router)
    app.include_router(knowledge_router)
    app.include_router(tickets_router)
    app.include_router(admin_router)
    app.include_router(usage_router)
    app.include_router(voice_router)
    app.include_router(connector_router)

    # 6. Standalone Hosted AI Widget Script Endpoint (Section 45)
    import os
    from fastapi.responses import FileResponse, Response

    widget_dist_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist-widget", "widget.js")
    )

    @app.get("/widget.js", include_in_schema=False)
    @app.get("/static/widget.js", include_in_schema=False)
    async def serve_widget_script():
        if os.path.exists(widget_dist_path):
            return FileResponse(
                widget_dist_path,
                media_type="application/javascript",
                headers={
                    "Cache-Control": "public, max-age=300",
                    "Access-Control-Allow-Origin": "*",
                },
            )
        return Response(content="// widget.js bundle not found", media_type="application/javascript", status_code=404)

    return app


app = create_app()
