from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), default="New Conversation", nullable=False)
    status = Column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, ARCHIVED

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="conversations")
    user = relationship("User", back_populates="conversations")
    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.created_at")
    summary = relationship("ConversationSummary", back_populates="conversation", uselist=False, cascade="all, delete-orphan")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, tool, system
    content = Column(Text, nullable=False)
    model = Column(String(100), nullable=True)
    token_usage = Column(JSON, nullable=True)  # {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60}
    tool_name = Column(String(100), nullable=True)
    tool_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), unique=True, nullable=False)
    summary_text = Column(Text, nullable=False)
    last_message_id = Column(String(36), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="summary")

