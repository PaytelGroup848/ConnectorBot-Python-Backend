import os
import sys
import asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

transport = ASGITransport(app=app)


async def run_all_tests():
    passed = 0
    failed = 0
    print("\n" + "=" * 60)
    print(" STARTING BACKEND INTEGRATION & SECURITY TEST SUITE")
    print("=" * 60)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # TEST 1: Health & System Probes
        try:
            res = await client.get("/health")
            assert res.status_code == 200 and res.json()["data"]["status"] == "UP"
            res_v = await client.get("/api/v1/system/version")
            assert res_v.status_code == 200 and res_v.json()["data"]["baseline"] == "/api/v1"
            res_s = await client.get("/api/v1/system/status")
            assert res_s.status_code == 200 and res_s.json()["data"]["database_status"] == "CONNECTED"
            print("  [PASS] Test 1: Health, Live & System Status Probes")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Test 1: Health Probes -> {e}")
            failed += 1

        # TEST 2: Session Exchange & Server-side Tenant Resolution
        try:
            payload = {
                "connector_token": "valid_mock_jwt_token_123",
                "email": "test_admin@example.com",
                "name": "Amit Sharma",
            }
            res = await client.post("/api/v1/session/exchange", json=payload)
            assert res.status_code == 200
            token = res.json()["data"]["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            res_me = await client.get("/api/v1/me", headers=headers)
            assert res_me.status_code == 200 and res_me.json()["data"]["email"] == "test_admin@example.com"

            res_ctx = await client.get("/api/v1/me/context", headers=headers)
            assert res_ctx.status_code == 200 and res_ctx.json()["data"]["role"] == "ADMIN"
            print("  [PASS] Test 2: Auth Session Exchange & Tenant Context")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Test 2: Session Exchange -> {e}")
            failed += 1

        # TEST 3: Chat Orchestration & Tool Calling
        try:
            chat_payload = {"message": "Mera Tally connection online hai ya nahi?"}
            res_chat = await client.post("/api/v1/chat", json=chat_payload, headers=headers)
            assert res_chat.status_code == 200
            chat_data = res_chat.json()
            assert chat_data["success"] is True
            assert len(chat_data["data"]["tool_calls"]) > 0
            assert chat_data["data"]["tool_calls"][0]["tool"] == "get_my_connection_status"
            print("  [PASS] Test 3: Chat Intent Detection & Live Tool Calling")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Test 3: Chat & Tools -> {e}")
            failed += 1

        # TEST 4: Ticket Creation & Idempotency Guard
        try:
            ticket_headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "test_idem_99999"}
            t_payload = {
                "subject": "Tally Sync Failed",
                "description": "Ledger error encountered during vouchers sync",
                "priority": "HIGH",
            }
            res1 = await client.post("/api/v1/tickets", json=t_payload, headers=ticket_headers)
            ticket1 = res1.json()["data"]
            res2 = await client.post("/api/v1/tickets", json=t_payload, headers=ticket_headers)
            ticket2 = res2.json()["data"]
            assert ticket1["ticket_id"] == ticket2["ticket_id"]
            print("  [PASS] Test 4: Idempotent Ticket Creation (No Duplicates)")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Test 4: Idempotency -> {e}")
            failed += 1

        # TEST 5: Knowledge Base Ingestion & RAG Retrieval
        try:
            doc_payload = {
                "title": "Tally Port 9000 Guide",
                "category": "Troubleshooting",
                "content": "To configure Tally Prime for Connector synchronization, enable HTTP XML on port 9000.",
            }
            res_doc = await client.post("/api/v1/knowledge/documents", json=doc_payload, headers=headers)
            assert res_doc.status_code == 200

            search_payload = {"query": "how to configure port 9000"}
            res_search = await client.post("/api/v1/knowledge/search", json=search_payload, headers=headers)
            results = res_search.json()["data"]["results"]
            assert len(results) > 0 and "9000" in results[0]["content"]
            print("  [PASS] Test 5: Knowledge Base Ingestion & RAG Vector/Keyword Search")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Test 5: RAG Search -> {e}")
            failed += 1

        # TEST 6: Admin Queue & Analytics
        try:
            res_adm = await client.get("/api/v1/admin/tickets", headers=headers)
            assert res_adm.status_code == 200
            res_ana = await client.get("/api/v1/admin/analytics", headers=headers)
            assert res_ana.status_code == 200 and "total_tickets" in res_ana.json()["data"]
            print("  [PASS] Test 6: Admin Support Queue & SLA Analytics")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Test 6: Admin APIs -> {e}")
            failed += 1

        # TEST 7: AI Usage & Quotas Metering
        try:
            res_u = await client.get("/api/v1/usage", headers=headers)
            assert res_u.status_code == 200 and "total_tokens" in res_u.json()["data"]
            res_lim = await client.get("/api/v1/usage/limits", headers=headers)
            assert res_lim.status_code == 200 and "daily_token_quota" in res_lim.json()["data"]
            print("  [PASS] Test 7: AI Usage Metering & Quotas")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] Test 7: Usage Metering -> {e}")
            failed += 1

    print("=" * 60)
    print(f" TEST SUITE SUMMARY: {passed} PASSED, {failed} FAILED")
    print("=" * 60 + "\n")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

