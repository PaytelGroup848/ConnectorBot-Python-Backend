from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from app.core.database import Base


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(36), nullable=True, index=True)
    
    provider = Column(String(50), default="patwatoliai", nullable=False)
    model = Column(String(100), default="gpt-4o", nullable=False)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    estimated_cost = Column(Float, default=0.0, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

