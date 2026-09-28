from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = Field(None, description="Active conversation UUID")
    message: str = Field(..., min_length=1, max_length=4000)
    company_name: Optional[str] = None
    company_id: Optional[str] = None
    connector_token: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    tally_port: Optional[int] = None


class ChatResponseData(BaseModel):
    conversation_id: str
    message_id: str
    role: str = "assistant"
    content: str
    citations: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []


class ChatFeedbackRequest(BaseModel):
    message_id: str
    rating: int = Field(..., ge=-1, le=1, description="1 for helpful, -1 for unhelpful")
    feedback_text: Optional[str] = None


class ChatRegenerateRequest(BaseModel):
    conversation_id: str
    message_id: str

