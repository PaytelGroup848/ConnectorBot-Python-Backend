import os
import sys
import asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

transport = ASGITransport(app=app)


async def test_voice_ai():
    print("\n" + "=" * 70)
    print(" TESTING VOICE AI MICROSERVICE (STT, NEURAL TTS & VOICE CHAT)")
    print("=" * 70)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test Voices List
        res_v = await client.get("/api/v1/voice/voices")
        assert res_v.status_code == 200
        voices = res_v.json()["data"]["voices"]
        assert len(voices) >= 4
        assert any(v["id"] == "hi-IN-MadhurNeural" for v in voices)
        assert any(v["id"] == "hi-IN-SwaraNeural" for v in voices)
        print(f"  [PASS] Voice Feature 1: Indian Neural Voices list verified ({len(voices)} voices available).")

        # 2. Test Text-to-Speech (TTS Synthesize)
        tts_payload = {
            "text": "Aapka Tally Prime connector online hai aur vouchers sync ho rahe hain.",
            "voice": "hi-IN-MadhurNeural",
        }
        res_tts = await client.post("/api/v1/voice/synthesize", json=tts_payload)
        assert res_tts.status_code == 200
        assert res_tts.headers["content-type"] == "audio/mpeg"
        audio_bytes = res_tts.content
        assert len(audio_bytes) > 5000, "Synthesized MP3 must contain valid audio payload"
        print(f"  [PASS] Voice Feature 2: Neural Text-to-Speech generated {len(audio_bytes)} bytes MP3 stream.")

        # 3. Test Audio Transcription (STT)
        res_token = await client.post(
            "/api/v1/session/exchange",
            json={"connector_token": "token_voice", "email": "voice_user@test.com", "name": "Voice User"},
        )
        token = res_token.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Mock voice file
        files = {"file": ("user_voice.webm", audio_bytes[:1000], "audio/webm")}
        res_stt = await client.post("/api/v1/voice/transcribe", headers=headers, files=files)
        assert res_stt.status_code == 200
        stt_data = res_stt.json()["data"]
        assert "text" in stt_data
        print(f"  [PASS] Voice Feature 3: Speech Transcription returned: '{stt_data['text']}'")

        # 4. Test End-to-End Voice Chat Pipeline
        voice_chat_files = {"file": ("question.webm", audio_bytes[:1000], "audio/webm")}
        voice_chat_data = {"voice": "hi-IN-SwaraNeural"}
        res_vc = await client.post(
            "/api/v1/voice/chat",
            headers=headers,
            files=voice_chat_files,
            data=voice_chat_data,
        )
        assert res_vc.status_code == 200
        vc_data = res_vc.json()["data"]
        assert "user_text" in vc_data
        assert "assistant_text" in vc_data
        assert "audio_base64" in vc_data
        assert len(vc_data["audio_base64"]) > 1000, "Voice chat response must include synthesized audio base64"
        print(f"  [PASS] Voice Feature 4: End-to-End Voice Chat pipeline executed perfectly (Audio Out: {len(vc_data['audio_base64'])} chars base64).")

    print("=" * 70)
    print(" ALL VOICE AI CAPABILITIES VERIFIED & OPERATIONAL!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(test_voice_ai())

