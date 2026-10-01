from datetime import timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.tenant import Tenant
from app.models.user import User
from app.core.security import create_access_token, decode_access_token
from app.core.config import settings
from app.core.exceptions import UnauthorizedException


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def exchange_session(
        self,
        connector_token: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ) -> dict:
        user_email = email
        if not user_email and connector_token:
            try:
                from jose import jwt
                unv = jwt.get_unverified_claims(connector_token)
                uid = unv.get("userId") or unv.get("sub") or unv.get("id")
                if uid:
                    user_email = f"user_{uid}@connector.cloudata.in"
            except Exception:
                pass
        user_email = user_email or "user@connector.cloudata.in"
        user_name = name or "Connector User"
        tenant_name = "Primary Organization"

        # Check existing user by email
        stmt = select(User).where(User.email == user_email)
        res = await self.db.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            # 1. Resolve primary tenant if available, or create new
            stmt_t = select(Tenant).order_by(Tenant.created_at).limit(1)
            res_t = await self.db.execute(stmt_t)
            tenant = res_t.scalar_one_or_none()
            if not tenant:
                tenant = Tenant(
                    name=tenant_name,
                    status="ACTIVE",
                    plan="Pro",
                    connector_tenant_id=f"cnt_{user_email.split('@')[0]}",
                )
                self.db.add(tenant)
                await self.db.flush()

            # 2. Create User
            is_guest = connector_token.startswith("guest_") or "guest" in user_email.lower()
            user = User(
                tenant_id=tenant.id,
                connector_user_id=f"usr_{user_email.split('@')[0]}",
                email=user_email,
                name=user_name,
                role="GUEST" if is_guest else "ADMIN",
                is_active=True,
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)

        # Generate AI access token
        access_token = create_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            role=user.role,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "role": user.role,
        }

    async def refresh_session(self, token: str) -> dict:
        payload = decode_access_token(token)
        if not payload:
            raise UnauthorizedException("Invalid or expired session token")

        user_id = payload.get("sub")
        tenant_id = payload.get("tenant_id")
        role = payload.get("role", "USER")

        new_token = create_access_token(
            subject=user_id,
            tenant_id=tenant_id,
            role=role,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        return {
            "access_token": new_token,
            "token_type": "Bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "role": role,
        }

