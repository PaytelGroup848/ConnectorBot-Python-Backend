from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="ACTIVE")
    plan = Column(String(50), nullable=False, default="Growth")
    connector_tenant_id = Column(String(100), unique=True, index=True, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="tenant", cascade="all, delete-orphan")
    documents = relationship("KnowledgeDocument", back_populates="tenant", cascade="all, delete-orphan")
    tickets = relationship("SupportTicket", back_populates="tenant", cascade="all, delete-orphan")

