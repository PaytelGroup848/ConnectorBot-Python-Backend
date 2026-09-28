from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    subject: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=5)
    priority: Optional[str] = Field("NORMAL", pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    conversation_id: Optional[str] = None
    ai_summary: Optional[Dict[str, Any]] = None


class TicketUpdate(BaseModel):
    description: Optional[str] = Field(None, min_length=5)


class TicketMessageCreate(BaseModel):
    message: str = Field(..., min_length=1)


class TicketActionPayload(BaseModel):
    status: str
    reply: Optional[str] = None


class TicketResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    conversation_id: Optional[str]
    subject: str
    description: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime

