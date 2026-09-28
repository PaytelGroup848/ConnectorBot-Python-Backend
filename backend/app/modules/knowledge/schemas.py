from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    category: str = Field("General", max_length=100)
    language: str = Field("en", max_length=10)
    content: Optional[str] = Field(None, description="Raw text or markdown content")


class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(None, pattern="^(DRAFT|ACTIVE|ARCHIVED)$")


class DocumentResponse(BaseModel):
    id: str
    tenant_id: Optional[str]
    title: str
    category: str
    language: str
    version: str
    status: str
    created_at: datetime
    updated_at: datetime


class SearchQueryRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = Field(5, ge=1, le=20)
    category: Optional[str] = None


class SearchResultItem(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    content: str
    score: float
    category: str

