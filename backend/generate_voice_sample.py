import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.modules.voice.service import voice_service


async def generate_samples():
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_samples")
    os.makedirs(output_dir, exist_ok=True)

    samples = [
        {
            "filename": "voice_sample_madhur_male.mp3",
            "voice": "hi-IN-MadhurNeural",
            "text": "Namaste! Main Connector AI Assistant hoon. Aapka Tally Prime connector successfully connected hai aur sabhi vouchers real-time sync ho rahe hain. Kya main aapke liye koi ledger ya voucher create karoon?",
            "speaker": "Madhur (Male, Hindi/Hinglish)",
        },
        {
            "filename": "voice_sample_swara_female.mp3",
            "voice": "hi-IN-SwaraNeural",
            "text": "Hello! Main aapki AI assistant Swara hoon. Maine aapka ledger balance aur GST calculation check kar liya hai, sab kuch completely balanced hai. Bataye main aapki kya madad kar sakti hoon?",
            "speaker": "Swara (Female, Hindi/Hinglish)",
        },
    ]

    print("=" * 65)
    print(" GENERATING NEURAL VOICE SAMPLES FOR TESTING")
    print("=" * 65)

    for item in samples:
        path = os.path.join(output_dir, item["filename"])
        print(f"\n[Synthesizing] {item['speaker']}...")
        print(f"Text: \"{item['text']}\"")
        audio_bytes = await voice_service.synthesize_speech(
            text=item["text"],
            voice=item["voice"],
        )
        with open(path, "wb") as f:
            f.write(audio_bytes)
        file_size_kb = len(audio_bytes) / 1024
        print(f"[SUCCESS] Saved to: {path} ({file_size_kb:.2f} KB)")

    print("\n" + "=" * 65)
    print(" All voice samples generated successfully!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(generate_samples())

