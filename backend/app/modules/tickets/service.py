from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from app.models.ticket import SupportTicket, TicketMessage, TicketEvent
from app.models.tenant import Tenant
from app.models.user import User
from app.middleware.tenant_context import get_or_resolve_default_tenant_and_user
from app.core.exceptions import NotFoundException, ForbiddenException, ConflictException


class TicketService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_ticket(
        self,
        tenant_id: str,
        user_id: str,
        subject: str,
        description: str,
        priority: str = "NORMAL",
        conversation_id: Optional[str] = None,
        ai_summary: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> SupportTicket:
        # Check idempotency
        if idempotency_key:
            stmt = select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.idempotency_key == idempotency_key,
            )
            res = await self.db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                return existing

        # Multi-tenant integrity guard: Ensure tenant_id and user_id exist in database
        tenant = await self.db.get(Tenant, tenant_id)
        if not tenant:
            def_tid, def_uid = await get_or_resolve_default_tenant_and_user(self.db)
            tenant_id = def_tid
            user_id = def_uid
        else:
            user = await self.db.get(User, user_id)
            if not user:
                _, def_uid = await get_or_resolve_default_tenant_and_user(self.db)
                user_id = def_uid

        ticket = SupportTicket(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            subject=subject,
            description=description,
            priority=priority,
            status="OPEN",
            idempotency_key=idempotency_key,
            ai_summary=ai_summary,
        )
        self.db.add(ticket)
        await self.db.flush()

        # Audit event
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type="CREATED",
            actor_id=user_id,
            metadata_={"priority": priority, "has_ai_summary": ai_summary is not None},
        )
        self.db.add(event)

        # Initial message
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_type="USER",
            sender_id=user_id,
            message=description,
            is_internal=False,
        )
        self.db.add(msg)

        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def list_user_tickets(
        self, tenant_id: str, user_id: str, page: int = 1, page_size: int = 50, include_all_customers: bool = True
    ) -> List[SupportTicket]:
        offset = (page - 1) * page_size
        stmt = select(SupportTicket).options(selectinload(SupportTicket.messages))
        if not include_all_customers:
            stmt = stmt.where(SupportTicket.tenant_id == tenant_id, SupportTicket.user_id == user_id)
        stmt = stmt.order_by(desc(SupportTicket.created_at)).offset(offset).limit(page_size)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def update_status_and_reply(
        self,
        tenant_id: str,
        user_id: str,
        ticket_id: str,
        status: str,
        engineer_reply: Optional[str] = None,
    ) -> SupportTicket:
        ticket = await self.get_authorized_ticket(tenant_id, user_id, ticket_id)
        ticket.status = status
        if status in ("RESOLVED", "CLOSED"):
            ticket.resolved_at = datetime.now(timezone.utc)
            ticket.closed_at = datetime.now(timezone.utc)

        if engineer_reply and engineer_reply.strip():
            msg = TicketMessage(
                ticket_id=ticket.id,
                sender_type="AGENT",
                sender_id="support_engineer_l2",
                message=engineer_reply.strip(),
                is_internal=False,
            )
            self.db.add(msg)

        event = TicketEvent(
            ticket_id=ticket.id,
            event_type=f"STATUS_{status}",
            actor_id="support_engineer_l2",
            metadata_={"new_status": status, "replied": bool(engineer_reply)},
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def get_authorized_ticket(
        self, tenant_id: str, user_id: str, ticket_id: str, allow_support_override: bool = True
    ) -> SupportTicket:
        """Enforces ticket lookup and allows Support Operations Console to resolve customer tickets."""
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.id == ticket_id)
            .options(selectinload(SupportTicket.messages), selectinload(SupportTicket.events))
        )
        res = await self.db.execute(stmt)
        ticket = res.scalar_one_or_none()
        if not ticket:
            raise NotFoundException("Ticket not found")
        if not allow_support_override and ticket.user_id != user_id:
            raise ForbiddenException("You do not have permission to view this ticket")
        return ticket

    async def add_customer_message(
        self, tenant_id: str, user_id: str, ticket_id: str, message: str
    ) -> TicketMessage:
        ticket = await self.get_authorized_ticket(tenant_id, user_id, ticket_id)
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_type="USER",
            sender_id=user_id,
            message=message,
            is_internal=False,
        )
        self.db.add(msg)
        ticket.status = "IN_PROGRESS"
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def close_ticket(self, tenant_id: str, user_id: str, ticket_id: str) -> SupportTicket:
        ticket = await self.get_authorized_ticket(tenant_id, user_id, ticket_id)
        ticket.status = "CLOSED"
        ticket.closed_at = datetime.now(timezone.utc)
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type="CLOSED_BY_USER",
            actor_id=user_id,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def reopen_ticket(self, tenant_id: str, user_id: str, ticket_id: str) -> SupportTicket:
        ticket = await self.get_authorized_ticket(tenant_id, user_id, ticket_id)
        ticket.status = "REOPENED"
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type="REOPENED_BY_USER",
            actor_id=user_id,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

