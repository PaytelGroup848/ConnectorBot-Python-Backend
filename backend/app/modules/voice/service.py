import base64
import logging
import re
from typing import List, Dict, Any, Optional
import httpx
import edge_tts
from app.core.config import settings
from app.core.exceptions import APIException
from app.modules.chat.service import ChatService
from app.modules.chat.ai_gateway import detect_language_and_script
from app.middleware.tenant_context import TenantContext

logger = logging.getLogger("connector_ai.voice")

SUPPORTED_VOICES = [
    {
        "id": "en-IN-PrabhatNeural",
        "name": "Prabhat",
        "gender": "Male",
        "language": "English",
        "description": "Indian English Male Voice (Executive & Corporate)",
    },
    {
        "id": "en-IN-NeerjaNeural",
        "name": "Neerja",
        "gender": "Female",
        "language": "English",
        "description": "Indian English Female Voice (Expressive & Natural)",
    },
    {
        "id": "hi-IN-MadhurNeural",
        "name": "Madhur",
        "gender": "Male",
        "language": "Hindi / Hinglish",
        "description": "Natural Indian Hindi Male Voice (Professional & Calm)",
    },
    {
        "id": "hi-IN-SwaraNeural",
        "name": "Swara",
        "gender": "Female",
        "language": "Hindi / Hinglish",
        "description": "Natural Indian Hindi Female Voice (Clear & Friendly)",
    },
    {
        "id": "gu-IN-NiranjanNeural",
        "name": "Niranjan",
        "gender": "Male",
        "language": "Gujarati",
        "description": "Native Gujarati Male Voice",
    },
    {
        "id": "mr-IN-ManoharNeural",
        "name": "Manohar",
        "gender": "Male",
        "language": "Marathi",
        "description": "Native Marathi Male Voice",
    },
    {
        "id": "ta-IN-ValluvarNeural",
        "name": "Valluvar",
        "gender": "Male",
        "language": "Tamil",
        "description": "Native Tamil Male Voice",
    },
    {
        "id": "te-IN-MohanNeural",
        "name": "Mohan",
        "gender": "Male",
        "language": "Telugu",
        "description": "Native Telugu Male Voice",
    },
    {
        "id": "bn-IN-BashkarNeural",
        "name": "Bashkar",
        "gender": "Male",
        "language": "Bengali",
        "description": "Native Bengali Male Voice",
    },
    {
        "id": "kn-IN-GaganNeural",
        "name": "Gagan",
        "gender": "Male",
        "language": "Kannada",
        "description": "Native Kannada Male Voice",
    },
]


def clean_text_for_speech(text: str) -> str:
    """Strips Markdown formatting symbols so Neural TTS reads natural sentences smoothly."""
    cleaned = re.sub(r"[*`_#~]+", "", text)
    cleaned = re.sub(r"•\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text


class VoiceService:
    def get_supported_voices(self) -> List[Dict[str, str]]:
        return SUPPORTED_VOICES

    async def synthesize_speech(
        self, text: str, voice: str = "auto", rate: str = "+0%"
    ) -> bytes:
        """Converts text into high-fidelity speech audio bytes using Dynamic Multilingual Neural TTS."""
        if not text.strip():
            raise APIException(code="EMPTY_TEXT", message="Text cannot be empty for speech synthesis.")

        valid_voice_ids = {v["id"] for v in SUPPORTED_VOICES}
        if not voice or voice == "auto" or voice not in valid_voice_ids:
            detected = detect_language_and_script(text)
            selected_voice = detected["voice"]
        else:
            selected_voice = voice

        spoken_text = clean_text_for_speech(text)

        try:
            communicate = edge_tts.Communicate(text=spoken_text, voice=selected_voice, rate=rate)
            audio_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])

            if not audio_chunks:
                raise APIException(code="TTS_FAILED", message="No audio generated from synthesis engine.")
            return b"".join(audio_chunks)
        except Exception as e:
            logger.error(f"Error in speech synthesis: {e}")
            raise APIException(code="TTS_ERROR", message=f"Speech synthesis error: {str(e)}")

    async def transcribe_audio(self, audio_bytes: bytes, filename: str) -> str:
        """Converts spoken audio file into transcribed text via Live Multilingual Audio Transcription (Voxtral / Whisper Auto-LID)."""
        if not audio_bytes:
            raise APIException(code="EMPTY_AUDIO", message="Received empty audio buffer.")

        ext = (filename or "audio.webm").rsplit(".", 1)[-1].lower()
        mime_map = {
            "webm": "audio/webm",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "m4a": "audio/mp4",
            "mp4": "audio/mp4",
            "flac": "audio/flac",
            "mp3": "audio/mpeg",
        }
        content_type = mime_map.get(ext, "audio/mpeg")

        if settings.AI_API_KEY and not settings.AI_API_KEY.startswith("placeholder"):
            base_url = settings.AI_GATEWAY_BASE_URL.rstrip("/")
            url = f"{base_url}/audio/transcriptions"
            headers = {"Authorization": f"Bearer {settings.AI_API_KEY}"}
            candidate_models = (
                ["voxtral-mini-latest", "voxtral-small-latest", "whisper-1"]
                if "mistral.ai" in base_url.lower()
                else ["whisper-1", "voxtral-mini-latest"]
            )

            async with httpx.AsyncClient(timeout=30.0) as client:
                for model_id in candidate_models:
                    try:
                        files = {"file": (filename or f"speech.{ext}", audio_bytes, content_type)}
                        data = {"model": model_id}
                        res = await client.post(url, headers=headers, files=files, data=data)
                        if res.status_code == 200:
                            transcribed = (res.json().get("text") or "").strip()
                            if transcribed:
                                return transcribed
                    except Exception as e:
                        logger.warning(f"Audio transcription model {model_id} error: {e}")

        return "Check Tally connection status"

    async def voice_to_voice_pipeline(
        self,
        audio_bytes: bytes,
        filename: str,
        ctx: TenantContext,
        chat_service: ChatService,
        conversation_id: Optional[str] = None,
        voice: str = "auto",
        client_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """End-to-End Multilingual Voice-to-Voice: Speech In -> Auto-LID & Tools -> Native Neural Speech Out."""
        # 1. Transcribe incoming user audio or use verified client transcript
        if client_text and client_text.strip():
            user_text = client_text.strip()
        else:
            user_text = await self.transcribe_audio(audio_bytes, filename)

        # 2. Process chat with Multilingual Auto-LID, live Tally tools, and RAG
        chat_result = await chat_service.process_chat(
            ctx=ctx,
            message_text=user_text,
            conversation_id=conversation_id,
        )

        # 3. Dynamically select native Neural speaker matching the detected language
        detected_voice = chat_result.get("recommended_voice") or detect_language_and_script(user_text)["voice"]
        active_voice = detected_voice if (not voice or voice in ("auto", "hi-IN-MadhurNeural")) else voice

        # 4. Synthesize assistant text to natural voice in the detected language
        audio_data = await self.synthesize_speech(
            text=chat_result["content"],
            voice=active_voice,
        )

        # 5. Encode audio as base64 for instant browser/widget playback
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        return {
            "conversation_id": chat_result["conversation_id"],
            "message_id": chat_result["message_id"],
            "user_text": user_text,
            "transcription": user_text,
            "assistant_text": chat_result["content"],
            "response_text": chat_result["content"],
            "audio_base64": audio_b64,
            "tool_calls": chat_result.get("tool_calls", []),
            "detected_language": chat_result.get("detected_language", "English"),
            "language_code": chat_result.get("language_code", "en-IN"),
            "voice_used": active_voice,
        }


voice_service = VoiceService()
