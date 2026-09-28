from fastapi import APIRouter, Depends, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.modules.auth.schemas import (
    SessionExchangeRequest,
    SessionTokenResponse,
    UserMeResponse,
    UserContextResponse,
)
from app.modules.auth.service import AuthService
from app.middleware.tenant_context import TenantContext, get_current_tenant_context
from app.models.user import User
from app.models.tenant import Tenant
from pydantic import BaseModel
from app.core.config import settings
from app.core.security import create_access_token
from app.core.exceptions import NotFoundException, UnauthorizedException

router = APIRouter(prefix="/api/v1", tags=["Authentication & Session"])


class AdminLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/admin-login", response_model=dict, summary="Authenticate Admin Console operator")
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_admin_login")
    if (
        payload.email.strip().lower() != settings.ADMIN_EMAIL.strip().lower()
        or payload.password != settings.ADMIN_PASSWORD
    ):
        raise UnauthorizedException("Invalid administrator email or password")

    tenant_id = "3733647b-374b-404a-8dc8-382b7de1abd3"
    user_id = "1e336198-e0dc-4ede-bf84-20165e022c67"
    try:
        res = await db.execute(select(Tenant).order_by(Tenant.created_at).limit(1))
        default_tenant = res.scalar_one_or_none()
        if default_tenant:
            tenant_id = str(default_tenant.id)

        user_res = await db.execute(select(User).where(User.tenant_id == tenant_id).limit(1))
        default_user = user_res.scalar_one_or_none()
        if default_user:
            user_id = str(default_user.id)
    except Exception:
        pass

    token = create_access_token(
        subject=user_id,
        tenant_id=tenant_id,
        role="ADMIN",
    )

    return {
        "success": True,
        "data": {
            "token": token,
            "user": {
                "id": user_id,
                "email": settings.ADMIN_EMAIL,
                "name": "CtrlBooks System Administrator",
                "role": "ADMIN",
                "tenant_id": tenant_id,
            },
        },
        "error": None,
        "request_id": request_id,
    }


@router.post("/session/exchange", response_model=dict, summary="Exchange Connector token for AI session")
async def session_exchange(
    payload: SessionExchangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_exchange")
    service = AuthService(db)
    token_data = await service.exchange_session(
        connector_token=payload.connector_token,
        email=payload.email,
        name=payload.name,
    )
    return {
        "success": True,
        "data": token_data,
        "error": None,
        "request_id": request_id,
    }


@router.post("/session/refresh", response_model=dict, summary="Refresh active AI session")
async def session_refresh(
    request: Request,
    authorization: str = Header(..., description="Current Bearer token"),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_refresh")
    token = authorization.replace("Bearer ", "").strip()
    service = AuthService(db)
    token_data = await service.refresh_session(token)
    return {
        "success": True,
        "data": token_data,
        "error": None,
        "request_id": request_id,
    }


@router.get("/me", response_model=dict, summary="Get current authenticated AI user profile")
async def get_me(
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_me")
    stmt = select(User).where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise NotFoundException("User profile not found")

    return {
        "success": True,
        "data": {
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/me/context", response_model=dict, summary="Get AI-safe tenant/user context")
async def get_me_context(
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_context")
    stmt_user = select(User).where(User.id == ctx.user_id)
    stmt_tenant = select(Tenant).where(Tenant.id == ctx.tenant_id)

    res_user = await db.execute(stmt_user)
    res_tenant = await db.execute(stmt_tenant)

    user = res_user.scalar_one_or_none()
    tenant = res_tenant.scalar_one_or_none()

    if not user or not tenant:
        raise NotFoundException("Context identity resolution failed")

    return {
        "success": True,
        "data": {
            "user_id": user.id,
            "tenant_id": tenant.id,
            "name": user.name,
            "role": user.role,
            "company_name": tenant.name,
            "plan": tenant.plan,
        },
        "error": None,
        "request_id": request_id,
    }

