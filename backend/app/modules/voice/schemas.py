from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize to speech")
    voice: Optional[str] = Field("auto", description="Voice identifier (e.g. auto, en-IN-PrabhatNeural, hi-IN-MadhurNeural, gu-IN-NiranjanNeural)")
    rate: Optional[str] = Field("+0%", description="Speaking speed rate adjustment (e.g. +10%, -10%)")
    format: Optional[str] = Field("audio", description="Output format: 'audio' (binary MP3 stream) or 'json' (Base64 audio JSON)")


class VoiceItem(BaseModel):
    id: str
    name: str
    gender: str
    language: str
    description: str


class VoiceChatResponse(BaseModel):
    conversation_id: str
    user_text: str
    transcription: str
    assistant_text: str
    response_text: str
    audio_base64: str
    detected_language: Optional[str] = "English"
    language_code: Optional[str] = "en-IN"
    voice_used: Optional[str] = "en-IN-PrabhatNeural"
    tool_calls: List[Dict[str, Any]] = []
