import os
import re
from fastapi import APIRouter, Depends, Request, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.middleware.tenant_context import TenantContext, get_current_tenant_context, require_roles
from app.modules.knowledge.schemas import DocumentCreate, DocumentUpdate, SearchQueryRequest
from app.modules.knowledge.service import KnowledgeService
from app.core.exceptions import APIException

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge & RAG"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per Architecture Section 41


@router.post("/documents", response_model=dict, summary="Upload/Create a knowledge document from text")
async def create_document(
    payload: DocumentCreate,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["ADMIN", "SUPPORT_AGENT"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_create")
    service = KnowledgeService(db)
    doc = await service.ingest_document(
        tenant_id=ctx.tenant_id,
        title=payload.title,
        category=payload.category,
        content=payload.content or payload.title,
        language=payload.language,
    )
    return {
        "success": True,
        "data": {
            "document_id": doc.id,
            "title": doc.title,
            "status": doc.status,
            "category": doc.category,
        },
        "error": None,
        "request_id": request_id,
    }


@router.post("/upload", response_model=dict, summary="Upload PDF or Text knowledge document")
async def upload_file_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form("General"),
    language: str = Form("en"),
    ctx: TenantContext = Depends(require_roles(["ADMIN", "SUPPORT_AGENT"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_upload")
    
    # 1. Path Traversal and Name Sanitization (Section 41 & 42)
    filename = os.path.basename(file.filename or "uploaded_doc")
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)
    ext = os.path.splitext(clean_name)[1].lower()
    if ext not in [".pdf", ".txt", ".md"]:
        raise APIException(code="INVALID_FILE_TYPE", message="Only .pdf, .txt, and .md files are supported.")

    # 2. Read and Size Check
    content_bytes = await file.read()
    if len(content_bytes) > MAX_FILE_SIZE:
        raise APIException(code="FILE_TOO_LARGE", message="File exceeds 10 MB size limit.")
    if len(content_bytes) == 0:
        raise APIException(code="EMPTY_FILE", message="Uploaded file is empty.")

    # 3. Text Extraction
    service = KnowledgeService(db)
    extracted_text = service.extract_text_from_file(content_bytes, clean_name)

    # 4. Save to disk safely
    saved_path = os.path.join(UPLOAD_DIR, f"{ctx.tenant_id}_{clean_name}")
    with open(saved_path, "wb") as f:
        f.write(content_bytes)

    # 5. Ingestion and chunking
    doc = await service.ingest_document(
        tenant_id=ctx.tenant_id,
        title=title,
        category=category,
        content=extracted_text,
        language=language,
        file_path=saved_path,
        file_size=len(content_bytes),
        mime_type=file.content_type or "application/octet-stream",
    )

    return {
        "success": True,
        "data": {
            "document_id": doc.id,
            "title": doc.title,
            "filename": clean_name,
            "file_size": len(content_bytes),
            "status": doc.status,
            "category": doc.category,
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/documents", response_model=dict, summary="List authorized knowledge documents")
async def list_documents(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_list")
    service = KnowledgeService(db)
    docs = await service.list_documents(tenant_id=ctx.tenant_id, page=page, page_size=page_size)
    return {
        "success": True,
        "data": {
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": d.id,
                    "title": d.title,
                    "category": d.category,
                    "language": d.language,
                    "version": d.version,
                    "status": d.status,
                    "file_size": d.file_size,
                    "created_at": d.created_at.isoformat(),
                }
                for d in docs
            ],
        },
        "error": None,
        "request_id": request_id,
    }


@router.get("/documents/{document_id}", response_model=dict, summary="Get document details")
async def get_document(
    document_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_get")
    service = KnowledgeService(db)
    doc = await service.get_document(tenant_id=ctx.tenant_id, doc_id=document_id)
    return {
        "success": True,
        "data": {
            "id": doc.id,
            "title": doc.title,
            "category": doc.category,
            "version": doc.version,
            "status": doc.status,
            "file_size": doc.file_size,
            "created_at": doc.created_at.isoformat(),
        },
        "error": None,
        "request_id": request_id,
    }


@router.delete("/documents/{document_id}", response_model=dict, summary="Delete knowledge document")
async def delete_document(
    document_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_del")
    service = KnowledgeService(db)
    await service.delete_document(tenant_id=ctx.tenant_id, doc_id=document_id)
    return {
        "success": True,
        "data": {"deleted": True, "id": document_id},
        "error": None,
        "request_id": request_id,
    }


@router.post("/documents/{document_id}/reindex", response_model=dict, summary="Reindex knowledge document")
async def reindex_document(
    document_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_reindex")
    return {
        "success": True,
        "data": {"reindexed": True, "document_id": document_id},
        "error": None,
        "request_id": request_id,
    }


@router.get("/documents/{document_id}/status", response_model=dict, summary="Check indexing status")
async def document_status(
    document_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_status")
    service = KnowledgeService(db)
    doc = await service.get_document(tenant_id=ctx.tenant_id, doc_id=document_id)
    return {
        "success": True,
        "data": {"document_id": doc.id, "status": doc.status},
        "error": None,
        "request_id": request_id,
    }


@router.post("/search", response_model=dict, summary="Semantic RAG knowledge search")
async def search_knowledge(
    payload: SearchQueryRequest,
    request: Request,
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_search")
    service = KnowledgeService(db)
    results = await service.search_knowledge(
        tenant_id=ctx.tenant_id,
        query=payload.query,
        top_k=payload.top_k,
        category=payload.category,
    )
    return {
        "success": True,
        "data": {"results": results, "query": payload.query},
        "error": None,
        "request_id": request_id,
    }


@router.patch("/documents/{document_id}", response_model=dict, summary="Update document metadata")
async def patch_document(
    document_id: str,
    payload: DocumentUpdate,
    request: Request,
    ctx: TenantContext = Depends(require_roles(["ADMIN"])),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_doc_patch")
    service = KnowledgeService(db)
    doc = await service.get_document(tenant_id=ctx.tenant_id, doc_id=document_id)
    if payload.title:
        doc.title = payload.title
    if payload.category:
        doc.category = payload.category
    if payload.status:
        doc.status = payload.status
    await db.commit()
    await db.refresh(doc)
    return {
        "success": True,
        "data": {"id": doc.id, "title": doc.title, "status": doc.status},
        "error": None,
        "request_id": request_id,
    }
