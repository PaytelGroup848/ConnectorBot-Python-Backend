from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from app.core.database import get_db
from app.middleware.tenant_context import TenantContext, get_current_tenant_context
from app.models.usage import AIUsage

router = APIRouter(prefix="/api/v1/usage", tags=["AI Usage & Quotas"])


@router.get("", response_model=dict, summary="Get current user's AI token usage")
async def get_user_usage(
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_usage")
    stmt = (
        select(
            func.sum(AIUsage.total_tokens).label("total_tokens"),
            func.sum(AIUsage.estimated_cost).label("total_cost"),
            func.count(AIUsage.id).label("total_queries"),
        )
        .where(AIUsage.tenant_id == ctx.tenant_id, AIUsage.user_id == ctx.user_id)
    )
    res = await db.execute(stmt)
    row = res.one()

    return {
        "success": True,
        "data": {
            "user_id": ctx.user_id,
            "total_tokens": row.total_tokens or 0,
            "estimated_cost_usd": round(row.total_cost or 0.0, 4),
            "total_queries": row.total_queries or 0,
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/summary", response_model=dict, summary="Get tenant-wide usage summary")
async def get_tenant_usage_summary(
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_usage_sum")
    stmt = (
        select(
            func.sum(AIUsage.total_tokens).label("total_tokens"),
            func.sum(AIUsage.estimated_cost).label("total_cost"),
            func.count(AIUsage.id).label("total_queries"),
        )
        .where(AIUsage.tenant_id == ctx.tenant_id)
    )
    res = await db.execute(stmt)
    row = res.one()

    return {
        "success": True,
        "data": {
            "tenant_id": ctx.tenant_id,
            "total_tokens": row.total_tokens or 0,
            "estimated_cost_usd": round(row.total_cost or 0.0, 4),
            "total_queries": row.total_queries or 0,
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/limits", response_model=dict, summary="Get active AI quotas and rate limits")
async def get_usage_limits(
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
):
    request_id = getattr(request.state, "request_id", "req_usage_lim")
    return {
        "success": True,
        "data": {
            "daily_token_quota": 500000,
            "daily_tokens_remaining": 485000,
            "concurrent_requests_limit": 5,
            "streaming_enabled": True,
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/history", response_model=dict, summary="Get historical token breakdown")
async def get_usage_history(
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_usage_hist")
    stmt = (
        select(AIUsage)
        .where(AIUsage.tenant_id == ctx.tenant_id, AIUsage.user_id == ctx.user_id)
        .order_by(desc(AIUsage.created_at))
        .limit(50)
    )
    res = await db.execute(stmt)
    items = res.scalars().all()

    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": u.id,
                    "model": u.model,
                    "tokens": u.total_tokens,
                    "cost": u.estimated_cost,
                    "created_at": u.created_at.isoformat(),
                }
                for u in items
            ]
        },
        "error": None,
        "request_id": request_id,
    }

