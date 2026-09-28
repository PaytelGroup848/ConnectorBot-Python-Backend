from typing import Optional, List
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.config import settings
from app.core.security import decode_access_token
from app.core.exceptions import UnauthorizedException, ForbiddenException


class TenantContext:
    def __init__(self, user_id: str, tenant_id: str, role: str):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role.upper()


async def get_optional_tenant_context(request: Request) -> Optional[TenantContext]:
    """Resolves identity server-side from Bearer token if present."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    role = payload.get("role", "USER")

    if not user_id or not tenant_id:
        return None

    context = TenantContext(user_id=user_id, tenant_id=tenant_id, role=role)
    request.state.tenant_context = context
    request.state.user_id = user_id
    request.state.tenant_id = tenant_id
    request.state.role = role
    return context


async def get_current_tenant_context(
    context: Optional[TenantContext] = Depends(get_optional_tenant_context),
) -> TenantContext:
    """Enforces authentication and extracts server-verified user & tenant context."""
    if not context:
        if settings.ENVIRONMENT == "development":
            return TenantContext(
                user_id="1e336198-e0dc-4ede-bf84-20165e022c67",
                tenant_id="3733647b-374b-404a-8dc8-382b7de1abd3",
                role="ADMIN",
            )
        raise UnauthorizedException("Valid authentication token required")
    return context

async def get_widget_or_tenant_context(
    request: Request,
    context: Optional[TenantContext] = Depends(get_optional_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """Dynamically resolves real user or falls back to the database's active primary organization."""
    # 1. Agar logged-in user ka valid token mila, toh wahi use karo
    if context:
        return context

    # 2. Agar token nahi hai, toh database se dynamically active tenant fetch karo (No Hardcoding)
    from sqlalchemy import select
    from app.models.tenant import Tenant
    from app.models.user import User

    res = await db.execute(select(Tenant).order_by(Tenant.created_at).limit(1))
    default_tenant = res.scalar_one_or_none()
    
    tenant_id = str(default_tenant.id) if default_tenant else "default-tenant"

    user_res = await db.execute(select(User).where(User.tenant_id == tenant_id).limit(1))
    default_user = user_res.scalar_one_or_none()
    user_id = str(default_user.id) if default_user else "default-user"

    return TenantContext(
        user_id=user_id,
        tenant_id=tenant_id,
        role="GUEST",
    )


def require_roles(allowed_roles: List[str]):
    """Role-based authorization dependency enforcing server-side permissions."""
    async def role_checker(
        context: TenantContext = Depends(get_current_tenant_context),
    ) -> TenantContext:
        normalized_allowed = [r.upper() for r in allowed_roles]
        if context.role not in normalized_allowed and context.role != "SUPERADMIN":
            raise ForbiddenException(
                f"Role '{context.role}' does not have sufficient permission for this action"
            )
        return context
    return role_checker
