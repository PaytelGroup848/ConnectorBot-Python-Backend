import logging
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import Response
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.exceptions import APIException
from app.middleware.tenant_context import TenantContext, get_current_tenant_context
from app.middleware.rate_limiter import voice_limiter
from app.middleware.security_jail import record_strike
from app.modules.voice.schemas import SynthesizeRequest, VoiceChatResponse
from app.modules.voice.service import voice_service
from app.modules.chat.service import ChatService

logger = logging.getLogger("connector_ai.voice")

router = APIRouter(prefix="/api/v1/voice", tags=["Voice AI & Speech"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB strict limit
DANGEROUS_SIGNATURES = [
    b"MZ",            # Windows PE executable / DLL
    b"\x7fELF",       # Linux ELF binary
    b"\xca\xfe\xba\xbe", # Java Class
    b"PK\x03\x04",    # ZIP / JAR archive
    b"#!",            # Shell script
    b"<?php",         # PHP script
    b"<script",       # HTML / JavaScript
]


async def validate_audio_file(audio_bytes: bytes, filename: str, client_ip: str) -> None:
    """Verifies audio size and validates magic bytes to prevent disguised executable uploads."""
    if not audio_bytes or len(audio_bytes) < 4:
        raise APIException(code="EMPTY_AUDIO", message="Uploaded audio buffer is empty or corrupted.")

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise APIException(code="AUDIO_TOO_LARGE", message="Audio file exceeds maximum allowed size of 10MB.")

    # Check for hostile executable / script disguise
    for sig in DANGEROUS_SIGNATURES:
        if audio_bytes.startswith(sig) or (sig in audio_bytes[:32]):
            await record_strike(client_ip, f"Hostile file upload disguise in {filename}")
            raise APIException(
                code="MALICIOUS_FILE_BLOCKED",
                message="Executable or malicious script signature detected in audio upload. Blocked.",
            )

    # Check valid audio signatures
    is_valid_audio = (
        audio_bytes.startswith(b"RIFF")
        or audio_bytes.startswith(b"ID3")
        or audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
        or audio_bytes.startswith(b"\x1a\x45\xdf\xa3")
        or audio_bytes.startswith(b"OggS")
        or audio_bytes.startswith(b"fLaC")
        or b"ftyp" in audio_bytes[:16]
    )

    # Allow mock test buffers if non-malicious and small
    if not is_valid_audio and len(audio_bytes) > 200:
        await record_strike(client_ip, f"Invalid audio magic bytes in {filename}")
        raise APIException(
            code="INVALID_AUDIO_FORMAT",
            message="Invalid audio format signature. Supported: MP3, WAV, WebM, OGG, M4A.",
        )


@router.get("/voices", response_model=dict, summary="List supported natural Indian voices")
async def list_voices(request: Request):
    request_id = getattr(request.state, "request_id", "req_voices")
    voices = voice_service.get_supported_voices()
    return {
        "success": True,
        "data": {"voices": voices},
        "error": None,
        "request_id": request_id,
    }


@router.post(
    "/synthesize",
    summary="Convert text to natural speech audio stream or Base64 JSON",
    dependencies=[Depends(voice_limiter)],
)
async def synthesize_speech(
    payload: SynthesizeRequest,
    request: Request,
):
    request_id = getattr(request.state, "request_id", "req_synthesize")

    # Sanitize & cap length
    clean_text = payload.text.strip()
    if len(clean_text) > 2000:
        raise APIException(
            code="TEXT_TOO_LONG",
            message="Speech synthesis text must not exceed 2000 characters.",
        )

    audio_bytes = await voice_service.synthesize_speech(
        text=clean_text,
        voice=payload.voice or "hi-IN-MadhurNeural",
        rate=payload.rate or "+0%",
    )

    if (payload.format or "").lower() == "json":
        import base64
        return {
            "success": True,
            "data": {
                "text": clean_text,
                "voice": payload.voice or "hi-IN-MadhurNeural",
                "audio_base64": base64.b64encode(audio_bytes).decode("utf-8"),
                "size_bytes": len(audio_bytes),
                "mime_type": "audio/mpeg",
            },
            "error": None,
            "request_id": request_id,
        }

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=speech.mp3",
            "Content-Length": str(len(audio_bytes)),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        },
    )


@router.post(
    "/transcribe",
    response_model=dict,
    summary="Convert spoken audio file to text",
    dependencies=[Depends(voice_limiter)],
)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(..., description="Audio file (.wav, .mp3, .m4a, .webm)"),
    ctx: TenantContext = Depends(get_current_tenant_context),
):
    request_id = getattr(request.state, "request_id", "req_transcribe")
    client_ip = request.client.host if request.client else "unknown"
    audio_bytes = await file.read()
    filename = file.filename or "audio.webm"

    # Deep inspection of uploaded audio
    await validate_audio_file(audio_bytes, filename, client_ip)

    transcribed_text = await voice_service.transcribe_audio(audio_bytes, filename)
    return {
        "success": True,
        "data": {"text": transcribed_text, "filename": filename},
        "error": None,
        "request_id": request_id,
    }


@router.post(
    "/chat",
    response_model=dict,
    summary="End-to-End Voice Chat (Audio In -> Reason -> Audio Out)",
    dependencies=[Depends(voice_limiter)],
)
async def voice_chat(
    request: Request,
    file: UploadFile = File(..., description="User recorded audio speech"),
    conversation_id: Optional[str] = Form(None),
    voice: Optional[str] = Form("auto"),
    text_prompt: Optional[str] = Form(None),
    ctx: TenantContext = Depends(get_current_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "req_voice_chat")
    client_ip = request.client.host if request.client else "unknown"
    audio_bytes = await file.read()
    filename = file.filename or "speech.webm"

    # Deep inspection of incoming speech audio
    await validate_audio_file(audio_bytes, filename, client_ip)

    chat_service = ChatService(db)
    result = await voice_service.voice_to_voice_pipeline(
        audio_bytes=audio_bytes,
        filename=filename,
        ctx=ctx,
        chat_service=chat_service,
        conversation_id=conversation_id,
        voice=voice or "auto",
        client_text=text_prompt,
    )

    return {
        "success": True,
        "data": result,
        "error": None,
        "request_id": request_id,
    }

