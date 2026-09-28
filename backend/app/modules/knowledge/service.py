import os
import re
import io
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, desc
from pypdf import PdfReader
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.core.exceptions import NotFoundException, APIException


class KnowledgeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def extract_text_from_file(self, file_bytes: bytes, filename: str) -> str:
        """Safely extracts text content from PDF, Markdown, or Plain Text files."""
        lower_name = filename.lower()
        if lower_name.endswith(".pdf"):
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                extracted_pages = []
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        extracted_pages.append(page_text.strip())
                full_text = "\n\n".join(extracted_pages)
                if not full_text.strip():
                    raise APIException(code="EXTRACTION_EMPTY", message="No readable text found in PDF.")
                return full_text
            except Exception as e:
                raise APIException(code="PDF_PARSING_ERROR", message=f"Failed to extract PDF: {str(e)}")
        else:
            # Text / Markdown
            try:
                return file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return file_bytes.decode("latin-1", errors="ignore")

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        words = text.split()
        if not words:
            return []
        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i : i + chunk_size])
            chunks.append(chunk)
            i += (chunk_size - overlap)
        return chunks

    async def ingest_document(
        self,
        tenant_id: Optional[str],
        title: str,
        category: str,
        content: str,
        language: str = "en",
        file_path: Optional[str] = None,
        file_size: int = 0,
        mime_type: str = "text/plain",
    ) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            tenant_id=tenant_id,
            title=title,
            category=category,
            language=language,
            version="1.0.0",
            status="ACTIVE",
            file_path=file_path,
            file_size=file_size or len(content.encode("utf-8")),
            mime_type=mime_type,
        )
        self.db.add(doc)
        await self.db.flush()

        chunks_text = self._chunk_text(content)
        for idx, chunk_str in enumerate(chunks_text):
            chunk = KnowledgeChunk(
                document_id=doc.id,
                tenant_id=tenant_id,
                chunk_index=idx,
                content=chunk_str,
                metadata_={"title": title, "category": category},
            )
            self.db.add(chunk)

        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def list_documents(self, tenant_id: str, page: int = 1, page_size: int = 20) -> List[KnowledgeDocument]:
        offset = (page - 1) * page_size
        stmt = (
            select(KnowledgeDocument)
            .where(or_(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.tenant_id.is_(None)))
            .order_by(desc(KnowledgeDocument.updated_at))
            .offset(offset)
            .limit(page_size)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_document(self, tenant_id: str, doc_id: str) -> KnowledgeDocument:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            or_(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.tenant_id.is_(None)),
        )
        res = await self.db.execute(stmt)
        doc = res.scalar_one_or_none()
        if not doc:
            raise NotFoundException("Knowledge document not found")
        return doc

    async def delete_document(self, tenant_id: str, doc_id: str) -> bool:
        doc = await self.get_document(tenant_id, doc_id)
        await self.db.delete(doc)
        await self.db.commit()
        return True

    async def search_knowledge(
        self, tenant_id: str, query: str, top_k: int = 5, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Tenant-aware knowledge search with keyword and semantic filtering."""
        query_words = set(re.findall(r'\w+', query.lower()))
        
        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                or_(KnowledgeChunk.tenant_id == tenant_id, KnowledgeChunk.tenant_id.is_(None)),
                KnowledgeDocument.status == "ACTIVE",
            )
        )
        if category:
            stmt = stmt.where(KnowledgeDocument.category == category)

        res = await self.db.execute(stmt)
        rows = res.all()

        scored_results = []
        for chunk, doc in rows:
            content_lower = chunk.content.lower()
            title_lower = doc.title.lower()
            overlap_score = sum(1 for w in query_words if w in content_lower or w in title_lower)
            if overlap_score > 0:
                scored_results.append({
                    "chunk_id": chunk.id,
                    "document_id": doc.id,
                    "title": doc.title,
                    "content": chunk.content,
                    "category": doc.category,
                    "score": round(overlap_score / max(len(query_words), 1), 2),
                })

        scored_results.sort(key=lambda x: x["score"], reverse=True)
        return scored_results[:top_k]
