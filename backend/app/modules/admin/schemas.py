from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AdminTicketUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(OPEN|IN_PROGRESS|WAITING_FOR_CUSTOMER|RESOLVED|CLOSED|REOPENED)$")
    priority: Optional[str] = Field(None, pattern="^(LOW|NORMAL|HIGH|URGENT)$")
    assigned_to: Optional[str] = None


class AdminAssignRequest(BaseModel):
    agent_id: str = Field(..., description="ID of agent to assign to")


class AdminReplyRequest(BaseModel):
    reply: str = Field(..., min_length=1)


class AdminNoteRequest(BaseModel):
    note: str = Field(..., min_length=1)


class AnalyticsSummaryResponse(BaseModel):
    total_tickets: int
    open_tickets: int
    resolved_tickets: int
    avg_resolution_hours: float
    total_conversations: int
    ai_resolved_percentage: float

