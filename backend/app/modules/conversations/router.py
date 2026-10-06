from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.middleware.tenant_context import TenantContext, get_current_tenant_context, get_widget_or_tenant_context
from app.modules.conversations.schemas import ConversationCreate, ConversationUpdate
from app.modules.conversations.service import ConversationService

router = APIRouter(prefix="/api/v1/conversations", tags=["Conversations"])


@router.post("", response_model=dict, summary="Create a new conversation thread")
async def create_conversation(
    payload: ConversationCreate,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_conv")
    service = ConversationService(db)
    conv = await service.create_conversation(tenant_id=ctx.tenant_id, user_id=ctx.user_id, title=payload.title or "New Conversation")
    return {
        "success": True,
        "data": {
            "conversation_id": conv.id,
            "title": conv.title,
            "status": conv.status,
            "created_at": conv.created_at.isoformat(),
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("", response_model=dict, summary="List current user's conversations")
async def list_conversations(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    ctx: TenantContext = Depends(get_widget_or_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_conv_list")
    if ctx.role == "GUEST":
        return {
            "success": True,
            "data": {
                "page": page,
                "page_size": page_size,
                "total": 0,
                "items": [],
            },
            "error": None,
            "request_id": request_id,
        }
    service = ConversationService(db)
    items, total = await service.list_conversations(tenant_id=ctx.tenant_id, user_id=ctx.user_id, page=page, page_size=page_size)
    return {
        "success": True,
        "data": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [
                {
                    "id": c.id,
                    "title": c.title,
                    "status": c.status,
                    "created_at": c.created_at.isoformat(),
                    "updated_at": c.updated_at.isoformat(),
                }
                for c in items
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/{conversation_id}", response_model=dict, summary="Get conversation messages & details")
async def get_conversation(
    conversation_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_widget_or_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_conv_detail")
    service = ConversationService(db)
    conv = await service.get_conversation_with_messages(tenant_id=ctx.tenant_id, user_id=ctx.user_id, conversation_id=conversation_id)
    return {
        "success": True,
        "data": {
            "id": conv.id,
            "title": conv.title,
            "status": conv.status,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "summary": conv.summary.summary_text if conv.summary else None,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "model": m.model,
                    "tool_name": m.tool_name,
                    "tool_metadata": m.tool_metadata,
                    "created_at": m.created_at.isoformat(),
                }
                for m in conv.messages
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.patch("/{conversation_id}", response_model=dict, summary="Update conversation metadata")
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_conv_update")
    service = ConversationService(db)
    conv = await service.update_conversation(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=conversation_id,
        title=payload.title,
        status=payload.status,
    )
    return {
        "success": True,
        "data": {
            "id": conv.id,
            "title": conv.title,
            "status": conv.status,
            "updated_at": conv.updated_at.isoformat(),
        },
        "error": None,
        "request_id": request_id,
    }


@router.delete("/{conversation_id}", response_model=dict, summary="Delete conversation")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_conv_del")
    service = ConversationService(db)
    await service.delete_conversation(tenant_id=ctx.tenant_id, user_id=ctx.user_id, conversation_id=conversation_id)
    return {
        "success": True,
        "data": {"deleted": True, "id": conversation_id},
        "error": None,
        "request_id": request_id,
    }


@router.post("/{conversation_id}/archive", response_model=dict, summary="Archive conversation")
async def archive_conversation(
    conversation_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_conv_arch")
    service = ConversationService(db)
    conv = await service.archive_conversation(tenant_id=ctx.tenant_id, user_id=ctx.user_id, conversation_id=conversation_id)
    return {
        "success": True,
        "data": {"archived": True, "id": conv.id, "status": conv.status},
        "error": None,
        "request_id": request_id,
    }

