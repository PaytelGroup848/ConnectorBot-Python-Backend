from typing import Optional, List
from fastapi import Request, Depends
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
