import os
import sys
import asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.core.crypto import encrypt_field, decrypt_field
from app.core.redis import cache_service

transport = ASGITransport(app=app)


async def test_fortress_security():
    print("\n" + "=" * 70)
    print(" TESTING FORTRESS ACTIVE DEFENSE (HONEYPOT, AUTO-BAN & CRYPTO)")
    print("=" * 70)

    # 1. Test Field-Level AES-256 Encryption
    secret_gstin = "27AAPFU0939F1ZV"
    encrypted = encrypt_field(secret_gstin)
    decrypted = decrypt_field(encrypted)

    assert encrypted != secret_gstin, "Ciphertext must not match plaintext"
    assert decrypted == secret_gstin, "Decrypted text must match original"
    print(f"  [PASS] Defense 1: AES-256 Field Encryption working (Cipher: {encrypted[:25]}...)")

    # 2. Test Honeypot Trap
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_trap = await client.get("/.env")
        assert res_trap.status_code == 200
        trap_data = res_trap.json()
        assert "🖕" in trap_data.get("warning", "")
        assert trap_data["error"]["code"] == "HONEYPOT_ACTIVATED"
        print("  [PASS] Defense 2: Honeypot Triggered. Troll response delivered successfully.")

        # 3. Test Security Jail (Subsequent requests from this banned client)
        res_blocked = await client.get("/health")
        assert res_blocked.status_code == 403
        blocked_data = res_blocked.json()
        assert "🖕" in blocked_data.get("warning", "")
        assert blocked_data["error"]["code"] == "IP_BANNED"
        print("  [PASS] Defense 3: Security Jail Active! Hostile IP terminated with 403 & troll shield.")

    # Clean up test ban in cache
    await cache_service.client.set("jail:banned:ip:127.0.0.1", "", ex=1)
    await cache_service.client.set("jail:banned:ip:testclient", "", ex=1)

    print("=" * 70)
    print(" ALL ACTIVE DEFENSE FORTRESS MODULES VERIFIED & OPERATIONAL!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(test_fortress_security())

