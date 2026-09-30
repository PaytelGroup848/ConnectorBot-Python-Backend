from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class SessionExchangeRequest(BaseModel):
    connector_token: str = Field(..., description="Connector auth token / session key to exchange")
    email: Optional[str] = Field(None, description="Optional verified email")
    name: Optional[str] = Field(None, description="Optional user name")


class SessionTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user_id: str
    tenant_id: str
    role: str


class UserMeResponse(BaseModel):
    user_id: str
    tenant_id: str
    name: str
    email: str
    role: str
    is_active: bool


class UserContextResponse(BaseModel):
    user_id: str
    tenant_id: str
    name: str
    role: str
    company_name: Optional[str] = None
    plan: str

