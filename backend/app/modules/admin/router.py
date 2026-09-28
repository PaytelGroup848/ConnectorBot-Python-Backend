from fastapi import APIRouter, Depends, Request, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.middleware.tenant_context import TenantContext, require_roles
from app.modules.admin.schemas import (
    AdminTicketUpdate,
    AdminAssignRequest,
    AdminReplyRequest,
    AdminNoteRequest,
)
from app.modules.admin.service import AdminService

router = APIRouter(prefix="/api/v1/admin", tags=["Admin & Support Operations"])


@router.get("/tickets", response_model=dict, summary="Search and filter support tickets across organization")
async def admin_list_tickets(
    request: Request,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: TenantContext = Depends(require_roles(["SUPPORT_AGENT", "ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_tickets")
    service = AdminService(db)
    items, total = await service.search_tickets(
        tenant_id=ctx.tenant_id,
        status=status,
        priority=priority,
        assigned_to=assigned_to,
        page=page,
        page_size=page_size,
    )
    return {
        "success": True,
        "data": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [
                {
                    "ticket_id": t.id,
                    "user_id": t.user_id,
                    "subject": t.subject,
                    "status": t.status,
                    "priority": t.priority,
                    "assigned_to": t.assigned_to,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.updated_at.isoformat(),
                }
                for t in items
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/tickets/{ticket_id}", response_model=dict, summary="Get full ticket detail with staff notes")
async def admin_get_ticket(
    ticket_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["SUPPORT_AGENT", "ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_ticket_get")
    service = AdminService(db)
    ticket = await service.get_ticket_detail(tenant_id=ctx.tenant_id, ticket_id=ticket_id)
    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "user_id": ticket.user_id,
            "subject": ticket.subject,
            "description": ticket.description,
            "status": ticket.status,
            "priority": ticket.priority,
            "assigned_to": ticket.assigned_to,
            "ai_summary": ticket.ai_summary,
            "created_at": ticket.created_at.isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
            "messages": [
                {
                    "id": m.id,
                    "sender_type": m.sender_type,
                    "sender_id": m.sender_id,
                    "message": m.message,
                    "is_internal": m.is_internal,
                    "created_at": m.created_at.isoformat(),
                }
                for m in ticket.messages
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.patch("/tickets/{ticket_id}", response_model=dict, summary="Update ticket status/priority/assignment")
async def admin_patch_ticket(
    ticket_id: str,
    payload: AdminTicketUpdate,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["SUPPORT_AGENT", "ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_patch")
    service = AdminService(db)
    ticket = await service.update_ticket(
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        ticket_id=ticket_id,
        status=payload.status,
        priority=payload.priority,
        assigned_to=payload.assigned_to,
    )
    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "priority": ticket.priority,
            "assigned_to": ticket.assigned_to,
        },
        "error": None,
        "request_id": request_id,
    }


@router.post("/tickets/{ticket_id}/assign", response_model=dict, summary="Assign ticket to agent")
async def admin_assign_ticket(
    ticket_id: str,
    payload: AdminAssignRequest,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["SUPPORT_AGENT", "ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_assign")
    service = AdminService(db)
    ticket = await service.assign_agent(
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        ticket_id=ticket_id,
        agent_id=payload.agent_id,
    )
    return {
        "success": True,
        "data": {"ticket_id": ticket.id, "assigned_to": ticket.assigned_to},
        "error": None,
        "request_id": request_id,
    }


@router.post("/tickets/{ticket_id}/reply", response_model=dict, summary="Send customer-visible agent reply")
async def admin_reply_ticket(
    ticket_id: str,
    payload: AdminReplyRequest,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["SUPPORT_AGENT", "ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_reply")
    service = AdminService(db)
    msg = await service.send_agent_reply(
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        ticket_id=ticket_id,
        reply=payload.reply,
    )
    return {
        "success": True,
        "data": {"message_id": msg.id, "ticket_id": ticket_id, "created_at": msg.created_at.isoformat()},
        "error": None,
        "request_id": request_id,
    }


@router.post("/tickets/{ticket_id}/internal-note", response_model=dict, summary="Create staff internal note")
async def admin_note_ticket(
    ticket_id: str,
    payload: AdminNoteRequest,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["SUPPORT_AGENT", "ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_note")
    service = AdminService(db)
    msg = await service.add_internal_note(
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        ticket_id=ticket_id,
        note=payload.note,
    )
    return {
        "success": True,
        "data": {"note_id": msg.id, "ticket_id": ticket_id, "created_at": msg.created_at.isoformat()},
        "error": None,
        "request_id": request_id,
    }


@router.get("/tickets/{ticket_id}/events", response_model=dict, summary="View ticket audit timeline")
async def admin_ticket_events(
    ticket_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["SUPPORT_AGENT", "ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_events")
    service = AdminService(db)
    ticket = await service.get_ticket_detail(tenant_id=ctx.tenant_id, ticket_id=ticket_id)
    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "events": [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "actor_id": e.actor_id,
                    "metadata": e.metadata_,
                    "created_at": e.created_at.isoformat(),
                }
                for e in ticket.events
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/analytics", response_model=dict, summary="Support volume and SLA analytics")
async def admin_analytics(
    request: Request,
    ctx: TenantContext = Depends(require_roles(["ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_adm_analytics")
    service = AdminService(db)
    data = await service.get_analytics(tenant_id=ctx.tenant_id)
    return {
        "success": True,
        "data": data,
        "error": None,
        "request_id": request_id,
    }

