from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    connector_user_id = Column(String(100), index=True, nullable=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="USER")  # USER, SUPPORT_AGENT, ADMIN, SUPERADMIN
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    tickets = relationship("SupportTicket", back_populates="user", foreign_keys="SupportTicket.user_id")

