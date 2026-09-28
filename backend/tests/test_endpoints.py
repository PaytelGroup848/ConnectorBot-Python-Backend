import os
import sys
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

transport = ASGITransport(app=app)


@pytest.mark.asyncio
async def test_health_endpoints():
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health basic
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["data"]["status"] == "UP"
        assert "request_id" in data

        # 2. System Version
        res_v = await client.get("/api/v1/system/version")
        assert res_v.status_code == 200
        data_v = res_v.json()
        assert data_v["data"]["baseline"] == "/api/v1"

        # 3. System Status
        res_s = await client.get("/api/v1/system/status")
        assert res_s.status_code == 200
        data_s = res_s.json()
        assert data_s["data"]["database_status"] == "CONNECTED"


@pytest.mark.asyncio
async def test_auth_and_session_exchange():
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "connector_token": "valid_mock_jwt_token_123",
            "email": "test_admin@example.com",
            "name": "Amit Sharma",
        }
        res = await client.post("/api/v1/session/exchange", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "access_token" in data["data"]
        token = data["data"]["access_token"]

        # Verify /api/v1/me
        headers = {"Authorization": f"Bearer {token}"}
        res_me = await client.get("/api/v1/me", headers=headers)
        assert res_me.status_code == 200
        assert res_me.json()["data"]["email"] == "test_admin@example.com"

        # Verify /api/v1/me/context
        res_ctx = await client.get("/api/v1/me/context", headers=headers)
        assert res_ctx.status_code == 200
        assert res_ctx.json()["data"]["role"] == "ADMIN"


@pytest.mark.asyncio
async def test_chat_and_tool_orchestration():
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Obtain auth token
        res_token = await client.post(
            "/api/v1/session/exchange",
            json={"connector_token": "token_chat", "email": "chat_user@test.com", "name": "Chat User"},
        )
        token = res_token.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Send query asking about connection status
        chat_payload = {"message": "Mera Tally connection online hai ya nahi?"}
        res_chat = await client.post("/api/v1/chat", json=chat_payload, headers=headers)
        assert res_chat.status_code == 200
        chat_data = res_chat.json()
        assert chat_data["success"] is True
        assert "conversation_id" in chat_data["data"]
        assert len(chat_data["data"]["tool_calls"]) > 0
        assert chat_data["data"]["tool_calls"][0]["tool"] == "get_my_connection_status"
        assert "Tally Prime" in chat_data["data"]["content"]


@pytest.mark.asyncio
async def test_ticket_creation_and_idempotency():
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_token = await client.post(
            "/api/v1/session/exchange",
            json={"connector_token": "token_ticket", "email": "ticket_user@test.com", "name": "Ticket User"},
        )
        token = res_token.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "unique_idem_key_999"}

        ticket_payload = {
            "subject": "Tally Sync Failed with Ledger Error",
            "description": "Sales ledger 18% GST was missing during sync",
            "priority": "HIGH",
        }

        # 1. Create ticket first time
        res1 = await client.post("/api/v1/tickets", json=ticket_payload, headers=headers)
        assert res1.status_code == 200
        ticket1 = res1.json()["data"]

        # 2. Resend with SAME Idempotency-Key
        res2 = await client.post("/api/v1/tickets", json=ticket_payload, headers=headers)
        assert res2.status_code == 200
        ticket2 = res2.json()["data"]

        # Verify idempotency (same ticket ID returned, no duplicate created)
        assert ticket1["ticket_id"] == ticket2["ticket_id"]


@pytest.mark.asyncio
async def test_knowledge_and_rag_search():
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_token = await client.post(
            "/api/v1/session/exchange",
            json={"connector_token": "token_admin", "email": "admin_rag@test.com", "name": "Admin RAG"},
        )
        token = res_token.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Document
        doc_payload = {
            "title": "Tally Port 9000 Configuration Guide",
            "category": "Troubleshooting",
            "content": "To configure Tally Prime for Connector synchronization, enable HTTP XML on port 9000 in F12 advanced configuration.",
        }
        res_doc = await client.post("/api/v1/knowledge/documents", json=doc_payload, headers=headers)
        assert res_doc.status_code == 200

        # 2. Search RAG
        search_payload = {"query": "how to configure port 9000 in Tally"}
        res_search = await client.post("/api/v1/knowledge/search", json=search_payload, headers=headers)
        assert res_search.status_code == 200
        results = res_search.json()["data"]["results"]
        assert len(results) > 0
        assert "9000" in results[0]["content"]


async def run_all_tests():
    print("\n" + "=" * 60)
    print(" RUNNING INTEGRATION TESTS FOR ALL CORE ENDPOINTS")
    print("=" * 60)
    await test_health_endpoints()
    print("  [PASS] 1. Health, Version & Status Endpoints")
    await test_auth_and_session_exchange()
    print("  [PASS] 2. Auth, Session Exchange, /me & /me/context")
    await test_chat_and_tool_orchestration()
    print("  [PASS] 3. Chat & Tool Orchestration")
    await test_ticket_creation_and_idempotency()
    print("  [PASS] 4. Ticket Lifecycle & Idempotency")
    await test_knowledge_and_rag_search()
    print("  [PASS] 5. Knowledge Base & RAG Vector Search")
    print("=" * 60)
    print(" ALL 5 CORE INTEGRATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_all_tests())

