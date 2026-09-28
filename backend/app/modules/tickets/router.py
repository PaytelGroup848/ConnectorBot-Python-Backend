from fastapi import APIRouter, Depends, Request, Query, Header
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.middleware.tenant_context import TenantContext, get_current_tenant_context
from app.modules.tickets.schemas import TicketCreate, TicketUpdate, TicketMessageCreate
from app.modules.tickets.service import TicketService

router = APIRouter(prefix="/api/v1/tickets", tags=["Customer Support Tickets"])


@router.post("", response_model=dict, summary="Create support ticket with idempotency support")
async def create_ticket(
    payload: TicketCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_create")
    service = TicketService(db)
    ticket = await service.create_ticket(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        subject=payload.subject,
        description=payload.description,
        priority=payload.priority or "NORMAL",
        conversation_id=payload.conversation_id,
        ai_summary=payload.ai_summary,
        idempotency_key=idempotency_key,
    )
    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "priority": ticket.priority,
            "subject": ticket.subject,
            "created_at": ticket.created_at.isoformat(),
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("", response_model=dict, summary="List current user's tickets")
async def list_tickets(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_list")
    service = TicketService(db)
    tickets = await service.list_user_tickets(tenant_id=ctx.tenant_id, user_id=ctx.user_id, page=page, page_size=page_size)
    return {
        "success": True,
        "data": {
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "ticket_id": t.id,
                    "subject": t.subject,
                    "status": t.status,
                    "priority": t.priority,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.updated_at.isoformat(),
                }
                for t in tickets
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/{ticket_id}", response_model=dict, summary="Get ticket details")
async def get_ticket(
    ticket_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_get")
    service = TicketService(db)
    ticket = await service.get_authorized_ticket(tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id)
    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "subject": ticket.subject,
            "description": ticket.description,
            "status": ticket.status,
            "priority": ticket.priority,
            "ai_summary": ticket.ai_summary,
            "created_at": ticket.created_at.isoformat(),
            "updated_at": ticket.updated_at.isoformat(),
        },
        "error": None,
        "request_id": request_id,
    }


@router.patch("/{ticket_id}", response_model=dict, summary="Update permitted customer ticket fields")
async def update_ticket(
    ticket_id: str,
    payload: TicketUpdate,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_patch")
    service = TicketService(db)
    ticket = await service.get_authorized_ticket(tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id)
    if payload.description:
        ticket.description = payload.description
    await db.commit()
    await db.refresh(ticket)
    return {
        "success": True,
        "data": {"ticket_id": ticket.id, "status": ticket.status},
        "error": None,
        "request_id": request_id,
    }


@router.get("/{ticket_id}/messages", response_model=dict, summary="List customer-visible ticket messages")
async def list_ticket_messages(
    ticket_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_msgs")
    service = TicketService(db)
    ticket = await service.get_authorized_ticket(tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id)
    # Filter out staff internal notes (Architecture Section 112)
    visible_msgs = [m for m in ticket.messages if not m.is_internal]
    return {
        "success": True,
        "data": {
            "ticket_id": ticket.id,
            "messages": [
                {
                    "id": m.id,
                    "sender_type": m.sender_type,
                    "sender_id": m.sender_id,
                    "message": m.message,
                    "created_at": m.created_at.isoformat(),
                }
                for m in visible_msgs
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.post("/{ticket_id}/messages", response_model=dict, summary="Add customer message/reply")
async def add_ticket_message(
    ticket_id: str,
    payload: TicketMessageCreate,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_msg_add")
    service = TicketService(db)
    msg = await service.add_customer_message(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id, message=payload.message
    )
    return {
        "success": True,
        "data": {"message_id": msg.id, "ticket_id": ticket_id, "created_at": msg.created_at.isoformat()},
        "error": None,
        "request_id": request_id,
    }


@router.post("/{ticket_id}/close", response_model=dict, summary="Close ticket")
async def close_ticket(
    ticket_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_close")
    service = TicketService(db)
    ticket = await service.close_ticket(tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id)
    return {
        "success": True,
        "data": {"ticket_id": ticket.id, "status": ticket.status},
        "error": None,
        "request_id": request_id,
    }


@router.post("/{ticket_id}/reopen", response_model=dict, summary="Reopen closed ticket")
async def reopen_ticket(
    ticket_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_ticket_reopen")
    service = TicketService(db)
    ticket = await service.reopen_ticket(tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id)
    return {
        "success": True,
        "data": {"ticket_id": ticket.id, "status": ticket.status},
        "error": None,
        "request_id": request_id,
    }

