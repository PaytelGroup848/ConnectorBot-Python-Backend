from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


def generate_ticket_id():
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    short_code = uuid.uuid4().hex[:4].upper()
    return f"CB-{date_str}-{short_code}"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(String(50), primary_key=True, default=generate_ticket_id)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String(20), default="NORMAL", nullable=False)  # LOW, NORMAL, HIGH, URGENT
    status = Column(String(50), default="OPEN", nullable=False)      # OPEN, IN_PROGRESS, WAITING_FOR_CUSTOMER, RESOLVED, CLOSED, REOPENED
    assigned_to = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=True)
    ai_summary = Column(JSON, nullable=True)  # Structured diagnostic context from AI

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="tickets")
    user = relationship("User", foreign_keys=[user_id], back_populates="tickets")
    assignee = relationship("User", foreign_keys=[assigned_to])
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketMessage.created_at")
    events = relationship("TicketEvent", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketEvent.created_at")


class TicketMessage(Base):
    __tablename__ = "support_ticket_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String(50), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type = Column(String(20), nullable=False)  # USER, AI, AGENT, SYSTEM
    sender_id = Column(String(36), nullable=False)
    message = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False, nullable=False)  # Staff-only internal note

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    ticket = relationship("SupportTicket", back_populates="messages")


class TicketEvent(Base):
    __tablename__ = "support_ticket_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String(50), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # CREATED, ASSIGNED, STATUS_CHANGED, NOTE_ADDED, RESOLVED, REOPENED
    actor_id = Column(String(36), nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    ticket = relationship("SupportTicket", back_populates="events")

