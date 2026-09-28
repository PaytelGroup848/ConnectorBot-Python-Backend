from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from app.core.database import Base


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)  # LOGIN_FAILED, PERMISSION_DENIED, RATE_LIMITED, PROMPT_INJECTION_ATTEMPT, IDOR_ATTEMPT
    severity = Column(String(20), default="LOW", nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    request_id = Column(String(100), nullable=True, index=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(255), nullable=True)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(100), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

