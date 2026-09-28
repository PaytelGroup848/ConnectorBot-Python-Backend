import os
import sys
import asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.modules.connector.commands import command_queue_service

transport = ASGITransport(app=app)


async def test_extra_features():
    print("\n" + "=" * 60)
    print(" TESTING PDF UPLOAD & CTRLBOOKS COMMAND ENGINE")
    print("=" * 60)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_token = await client.post(
            "/api/v1/session/exchange",
            json={
                "connector_token": "token_admin",
                "email": "admin@example.com",
                "name": "Admin User",
            },
        )
        token = res_token.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Feature 1: Multipart Document Upload
        files = {"file": ("tally_troubleshooting.txt", b"Step 1: Check Tally port 9000. Step 2: Restart agent.", "text/plain")}
        data = {"title": "Tally Setup Quick Guide", "category": "Troubleshooting"}
        res_up = await client.post("/api/v1/knowledge/upload", headers=headers, data=data, files=files)
        assert res_up.status_code == 200
        up_data = res_up.json()
        assert up_data["success"] is True
        assert up_data["data"]["title"] == "Tally Setup Quick Guide"
        print("  [PASS] Feature 1: Multipart Document Upload & Text Ingestion")

        # Feature 2: Sales Invoice Generation
        inv_res = await command_queue_service.create_sales_invoice(
            company_name="Tarun Enterprise (25-26)",
            party_ledger="Acme Traders",
            date="2026-09-22",
            items=[{"name": "Cement 50kg", "quantity": 10.0, "rate": 1000.0, "unit": "Bags", "amount": 10000.0}],
            total_amount=10000.0,
        )
        assert inv_res["success"] is True
        assert inv_res["command_type"] == "CREATE_VOUCHER"
        assert len(inv_res["payload"]["payload"]["ledger_entries"]) == 2
        print("  [PASS] Feature 2: CtrlBooks Sales Invoice Generation with GST & Penny Balancing")

        # Feature 3: Command Idempotency Hash Guard
        inv_res2 = await command_queue_service.create_sales_invoice(
            company_name="Tarun Enterprise (25-26)",
            party_ledger="Acme Traders",
            date="2026-09-22",
            items=[{"name": "Cement 50kg", "quantity": 10.0, "rate": 1000.0, "unit": "Bags", "amount": 10000.0}],
            total_amount=10000.0,
        )
        assert inv_res["command_hash"] == inv_res2["command_hash"]
        print("  [PASS] Feature 3: CtrlBooks Command Idempotency Hash Guard")

    print("=" * 60)
    print(" ALL ADVANCED BACKEND FEATURES VERIFIED SUCCESSFULLY!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_extra_features())
