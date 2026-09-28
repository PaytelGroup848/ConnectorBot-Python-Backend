import time
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from app.core.redis import cache_service
from app.core.config import settings

router = APIRouter(tags=["Health & Operations"])
START_TIME = time.time()


@router.get("/health", summary="Basic health probe")
async def basic_health(request: Request):
    request_id = getattr(request.state, "request_id", "req_health")
    return {
        "success": True,
        "data": {"status": "UP"},
        "error": None,
        "request_id": request_id,
    }


@router.get("/health/live", summary="PM2 / Kubernetes Liveness probe")
async def liveness_probe(request: Request):
    request_id = getattr(request.state, "request_id", "req_live")
    return {
        "success": True,
        "data": {"live": True},
        "error": None,
        "request_id": request_id,
    }


@router.get("/health/ready", summary="Readiness probe validating DB & Cache")
async def readiness_probe(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", "req_ready")
    
    # 1. Check Database
    db_healthy = False
    try:
        res = await db.execute(text("SELECT 1;"))
        db_healthy = (res.scalar() == 1)
    except Exception:
        db_healthy = False

    # 2. Check Cache
    cache_healthy = await cache_service.client.ping()

    ready = db_healthy and cache_healthy
    return {
        "success": ready,
        "data": {
            "ready": ready,
            "database": "UP" if db_healthy else "DOWN",
            "cache": "UP" if cache_healthy else "DOWN",
        },
        "error": None if ready else {"code": "DEPENDENCY_ERROR", "message": "Required dependencies unavailable"},
        "request_id": request_id,
    }


@router.get("/api/v1/system/status", summary="Controlled system status")
async def system_status(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", "req_status")
    
    db_ok = True
    try:
        await db.execute(text("SELECT 1;"))
    except Exception:
        db_ok = False

    return {
        "success": True,
        "data": {
            "environment": settings.ENVIRONMENT,
            "database_status": "CONNECTED" if db_ok else "DISCONNECTED",
            "uptime_seconds": int(time.time() - START_TIME),
            "ai_gateway": settings.AI_GATEWAY_BASE_URL,
            "connector_api": settings.CONNECTOR_API_BASE_URL,
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/api/v1/system/version", summary="Version & build metadata")
async def system_version(request: Request):
    request_id = getattr(request.state, "request_id", "req_version")
    return {
        "success": True,
        "data": {
            "version": "1.0.0",
            "baseline": "/api/v1",
            "name": settings.PROJECT_NAME,
        },
        "error": None,
        "request_id": request_id,
    }

