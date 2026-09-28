from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Integer, BigInteger, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(100), default="General", nullable=False)  # FAQ, Troubleshooting, Guides, ReleaseNotes
    language = Column(String(10), default="en", nullable=False)        # en, hi, hinglish
    version = Column(String(20), default="1.0.0", nullable=False)
    status = Column(String(50), default="DRAFT", nullable=False)       # DRAFT, PROCESSING, ACTIVE, FAILED, ARCHIVED
    source = Column(String(255), nullable=True)
    file_path = Column(String(500), nullable=True)
    file_size = Column(BigInteger, default=0, nullable=False)
    mime_type = Column(String(100), default="text/plain", nullable=False)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="documents")
    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan", order_by="KnowledgeChunk.chunk_index")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True, index=True)  # Denormalized for fast filtering
    chunk_index = Column(Integer, default=0, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=True)  # List of floats for vector representation
    metadata_ = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    document = relationship("KnowledgeDocument", back_populates="chunks")

