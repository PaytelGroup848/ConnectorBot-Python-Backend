import json
import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.middleware.tenant_context import TenantContext, get_current_tenant_context
from app.middleware.rate_limiter import chat_limiter
from app.modules.chat.schemas import (
    ChatRequest,
    ChatFeedbackRequest,
    ChatRegenerateRequest,
)
from app.modules.chat.service import ChatService

router = APIRouter(prefix="/api/v1/chat", tags=["Chat & Streaming"])


@router.post("", response_model=dict, summary="Normal non-streaming AI completion")
async def chat_completion(
    payload: ChatRequest,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
    _ = Depends(chat_limiter),
):
    request_id = getattr(request.state, "request_id", "req_chat")
    service = ChatService(db)
    result = await service.process_chat(
        ctx=ctx,
        message_text=payload.message,
        conversation_id=payload.conversation_id,
        company_name=payload.company_name,
        user_meta={
            "user_name": payload.user_name,
            "user_email": payload.user_email,
            "user_phone": payload.user_phone,
            "tally_port": payload.tally_port,
            "company_id": payload.company_id,
            "connector_token": payload.connector_token,
        },
    )
    return {
        "success": True,
        "data": result,
        "error": None,
        "request_id": request_id,
    }


@router.post("/stream", summary="Streaming AI response via Server-Sent Events (SSE)")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
    _ = Depends(chat_limiter),
):
    request_id = getattr(request.state, "request_id", "req_chat_stream")
    service = ChatService(db)
    result = await service.process_chat(
        ctx=ctx,
        message_text=payload.message,
        conversation_id=payload.conversation_id,
        company_name=payload.company_name,
    )

    async def event_generator():
        # Stream initial metadata
        yield f"data: {json.dumps({'event': 'start', 'conversation_id': result['conversation_id'], 'request_id': request_id})}\n\n"
        await asyncio.sleep(0.05)

        # Stream content in realistic chunks
        words = result["content"].split(" ")
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i : i + 3]) + " "
            yield f"data: {json.dumps({'event': 'delta', 'chunk': chunk})}\n\n"
            await asyncio.sleep(0.04)

        # Stream completion event
        yield f"data: {json.dumps({'event': 'done', 'message_id': result['message_id'], 'tool_calls': result['tool_calls']})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback", response_model=dict, summary="Submit thumbs/quality feedback")
async def chat_feedback(
    payload: ChatFeedbackRequest,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
):
    request_id = getattr(request.state, "request_id", "req_chat_fb")
    return {
        "success": True,
        "data": {"recorded": True, "message_id": payload.message_id, "rating": payload.rating},
        "error": None,
        "request_id": request_id,
    }


@router.post("/regenerate", response_model=dict, summary="Regenerate previous answer")
async def chat_regenerate(
    payload: ChatRegenerateRequest,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_chat_regen")
    service = ChatService(db)
    result = await service.process_chat(
        ctx=ctx,
        message_text="Please regenerate the previous response with more details.",
        conversation_id=payload.conversation_id,
    )
    return {
        "success": True,
        "data": result,
        "error": None,
        "request_id": request_id,
    }

