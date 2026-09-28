from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: Optional[str] = Field("New Conversation", max_length=255)


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, pattern="^(ACTIVE|ARCHIVED)$")


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    model: Optional[str] = None
    tool_name: Optional[str] = None
    created_at: datetime


class ConversationResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: List[MessageResponse] = []
    summary: Optional[str] = None

