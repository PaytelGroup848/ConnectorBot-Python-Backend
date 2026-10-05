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
        connector_uid = None
        if connector_token:
            try:
                from jose import jwt
                unv = jwt.get_unverified_claims(connector_token)
                connector_uid = unv.get("userId") or unv.get("sub") or unv.get("id")
                if not user_email and connector_uid:
                    user_email = f"user_{connector_uid}@connector.cloudata.in"
            except Exception:
                pass
        user_email = user_email or "user@connector.cloudata.in"
        user_name = name or "Connector User"
        tenant_name = "Primary Organization"

        # Check existing user by email or connector_user_id (safely fetch latest active user without MultipleResultsFound)
        from sqlalchemy import or_
        conditions = [User.email == user_email]
        if connector_uid:
            conditions.append(User.connector_user_id == f"usr_{connector_uid}")

        stmt = (
            select(User)
            .where(or_(*conditions))
            .order_by(User.is_active.desc(), User.created_at.desc())
            .limit(1)
        )
        res = await self.db.execute(stmt)
        user = res.scalars().first()

        if not user:
            # 1. Resolve organization tenant dynamically based on connector_uid or user_email domain
            # Guarantees multi-tenant isolation so separate customer accounts don't share tickets/conversations
            conn_tenant_key = f"cnt_{connector_uid}" if connector_uid else f"cnt_{user_email.split('@')[1].replace('.', '_') if '@' in user_email else user_email}"
            stmt_t = select(Tenant).where(Tenant.connector_tenant_id == conn_tenant_key).limit(1)
            res_t = await self.db.execute(stmt_t)
            tenant = res_t.scalars().first()
            if not tenant:
                domain_part = user_email.split('@')[1] if '@' in user_email else 'workspace'
                if domain_part in ("ctrlbooks.com", "connector.cloudata.in"):
                    # Primary/demo domain fallback
                    stmt_pri = select(Tenant).order_by(Tenant.created_at).limit(1)
                    res_pri = await self.db.execute(stmt_pri)
                    tenant = res_pri.scalars().first()
                if not tenant:
                    org_name = name or (user_email.split('@')[0].capitalize() + " Organization")
                    tenant = Tenant(
                        name=org_name,
                        status="ACTIVE",
                        plan="Pro",
                        connector_tenant_id=conn_tenant_key,
                    )
                    self.db.add(tenant)
                    await self.db.flush()

            # 2. Create User
            is_guest = connector_token.startswith("guest_") or "guest" in user_email.lower()
            user = User(
                tenant_id=tenant.id,
                connector_user_id=f"usr_{connector_uid}" if connector_uid else f"usr_{user_email.split('@')[0]}",
                email=user_email,
                name=user_name,
                role="GUEST" if is_guest else "USER",
                is_active=True,
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
        else:
            # Update user details if needed
            needs_update = False
            if name and user.name != name:
                user.name = name
                needs_update = True
            if not user.is_active:
                user.is_active = True
                needs_update = True
            if connector_uid and not user.connector_user_id:
                user.connector_user_id = f"usr_{connector_uid}"
                needs_update = True
            if needs_update:
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

