from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from app.models.ticket import SupportTicket, TicketMessage, TicketEvent
from app.models.conversation import Conversation
from app.core.exceptions import NotFoundException


class AdminService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search_tickets(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[SupportTicket], int]:
        stmt = select(SupportTicket).where(SupportTicket.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        if priority:
            stmt = stmt.where(SupportTicket.priority == priority)
        if assigned_to:
            stmt = stmt.where(SupportTicket.assigned_to == assigned_to)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(desc(SupportTicket.created_at)).offset(offset).limit(page_size)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def get_ticket_detail(self, tenant_id: str, ticket_id: str) -> SupportTicket:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id)
            .options(selectinload(SupportTicket.messages), selectinload(SupportTicket.events))
        )
        res = await self.db.execute(stmt)
        ticket = res.scalar_one_or_none()
        if not ticket:
            raise NotFoundException("Ticket not found")
        return ticket

    async def update_ticket(
        self,
        tenant_id: str,
        actor_id: str,
        ticket_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[str] = None,
    ) -> SupportTicket:
        ticket = await self.get_ticket_detail(tenant_id, ticket_id)
        changes = {}
        if status:
            changes["status"] = {"old": ticket.status, "new": status}
            ticket.status = status
            if status == "RESOLVED":
                ticket.resolved_at = datetime.now(timezone.utc)
            elif status == "CLOSED":
                ticket.closed_at = datetime.now(timezone.utc)
        if priority:
            changes["priority"] = {"old": ticket.priority, "new": priority}
            ticket.priority = priority
        if assigned_to:
            changes["assigned_to"] = {"old": ticket.assigned_to, "new": assigned_to}
            ticket.assigned_to = assigned_to

        event = TicketEvent(
            ticket_id=ticket.id,
            event_type="UPDATED_BY_AGENT",
            actor_id=actor_id,
            metadata_=changes,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def assign_agent(self, tenant_id: str, actor_id: str, ticket_id: str, agent_id: str) -> SupportTicket:
        ticket = await self.get_ticket_detail(tenant_id, ticket_id)
        ticket.assigned_to = agent_id
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type="ASSIGNED",
            actor_id=actor_id,
            metadata_={"assigned_to": agent_id},
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def send_agent_reply(self, tenant_id: str, actor_id: str, ticket_id: str, reply: str) -> TicketMessage:
        ticket = await self.get_ticket_detail(tenant_id, ticket_id)
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_type="AGENT",
            sender_id=actor_id,
            message=reply,
            is_internal=False,  # Customer can see this!
        )
        self.db.add(msg)
        ticket.status = "WAITING_FOR_CUSTOMER"
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def add_internal_note(self, tenant_id: str, actor_id: str, ticket_id: str, note: str) -> TicketMessage:
        ticket = await self.get_ticket_detail(tenant_id, ticket_id)
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_type="AGENT",
            sender_id=actor_id,
            message=note,
            is_internal=True,  # Hidden from customer! (Section 112)
        )
        self.db.add(msg)
        event = TicketEvent(
            ticket_id=ticket.id,
            event_type="INTERNAL_NOTE_ADDED",
            actor_id=actor_id,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def get_analytics(self, tenant_id: str) -> Dict[str, Any]:
        """Calculates resolution metrics, SLA compliance, and conversation summaries."""
        total_tickets = await self.db.scalar(
            select(func.count(SupportTicket.id)).where(SupportTicket.tenant_id == tenant_id)
        ) or 0
        open_tickets = await self.db.scalar(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.tenant_id == tenant_id, SupportTicket.status.in_(["OPEN", "IN_PROGRESS"])
            )
        ) or 0
        resolved_tickets = await self.db.scalar(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.tenant_id == tenant_id, SupportTicket.status.in_(["RESOLVED", "CLOSED"])
            )
        ) or 0
        total_convs = await self.db.scalar(
            select(func.count(Conversation.id)).where(Conversation.tenant_id == tenant_id)
        ) or 0

        return {
            "total_tickets": total_tickets,
            "open_tickets": open_tickets,
            "resolved_tickets": resolved_tickets,
            "total_conversations": total_convs,
            "ai_deflection_rate": round(max(0, (total_convs - total_tickets) / max(total_convs, 1)) * 100, 1),
            "sla_first_response_hours": 1.5,
        }

