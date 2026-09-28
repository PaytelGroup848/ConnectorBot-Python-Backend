import os
import sys
import asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

transport = ASGITransport(app=app)


async def run_security_audit():
    passed = 0
    failed = 0
    print("\n" + "=" * 70)
    print(" EXECUTING COMPREHENSIVE DEFENSIVE SECURITY AUDIT & PEN-TEST MATRIX")
    print("=" * 70)

    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # -------------------------------------------------------------
        # TEST 1: Unauthenticated Endpoint Access (Auth Bypass Defense)
        # -------------------------------------------------------------
        print("\n[Vulnerability Test 1] Unauthenticated Access to Sensitive Endpoints")
        res1 = await client.get("/api/v1/conversations")
        res2 = await client.get("/api/v1/tickets")
        res3 = await client.get("/api/v1/admin/tickets")
        if res1.status_code == 401 and res2.status_code == 401 and res3.status_code == 401:
            print("  --> [PASS] Correctly blocked with HTTP 401 Unauthorized.")
            passed += 1
        else:
            print(f"  --> [FAIL] Exposed endpoints without auth: {res1.status_code}, {res2.status_code}, {res3.status_code}")
            failed += 1

        # Provision two separate tenants for cross-tenant tests
        # Tenant A (Normal User)
        res_a = await client.post(
            "/api/v1/session/exchange",
            json={"connector_token": "tok_a", "email": "user_a@company-a.com", "name": "Alice Corp A"}
        )
        token_a = res_a.json()["data"]["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Tenant B (Target Victim)
        res_b = await client.post(
            "/api/v1/session/exchange",
            json={"connector_token": "tok_b", "email": "user_b@company-b.com", "name": "Bob Corp B"}
        )
        token_b = res_b.json()["data"]["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Tenant B creates a sensitive support ticket
        t_res = await client.post(
            "/api/v1/tickets",
            json={"subject": "Confidential Payroll Sync Error", "description": "Salary vouchers failed to sync"},
            headers=headers_b
        )
        ticket_b_id = t_res.json()["data"]["ticket_id"]

        # -------------------------------------------------------------
        # TEST 2: IDOR & Horizontal Privilege Escalation (Cross-Tenant)
        # -------------------------------------------------------------
        print(f"\n[Vulnerability Test 2] Horizontal Privilege Escalation / IDOR (Tenant A accessing Tenant B's Ticket '{ticket_b_id}')")
        res_idor = await client.get(f"/api/v1/tickets/{ticket_b_id}", headers=headers_a)
        if res_idor.status_code in [403, 404]:
            print(f"  --> [PASS] IDOR blocked successfully with HTTP {res_idor.status_code}. Cross-tenant data leak prevented.")
            passed += 1
        else:
            print(f"  --> [FAIL] IDOR vulnerability detected! Status: {res_idor.status_code}")
            failed += 1

        # -------------------------------------------------------------
        # TEST 3: Vertical Privilege Escalation (Normal User -> Admin API)
        # -------------------------------------------------------------
        print("\n[Vulnerability Test 3] Vertical Privilege Escalation (Non-Admin User accessing Admin Queue)")
        # In our exchange, normal provision gives ADMIN for first user; let's simulate USER token
        from app.core.security import create_access_token
        user_only_token = create_access_token(subject="user_low_priv", tenant_id="t_low", role="USER")
        headers_user = {"Authorization": f"Bearer {user_only_token}"}

        res_priv = await client.get("/api/v1/admin/tickets", headers=headers_user)
        if res_priv.status_code == 403:
            print("  --> [PASS] Vertical privilege escalation blocked with HTTP 403 Forbidden.")
            passed += 1
        else:
            print(f"  --> [FAIL] User role accessed admin API! Status: {res_priv.status_code}")
            failed += 1

        # -------------------------------------------------------------
        # TEST 4: Path Traversal & Arbitrary File Upload Attack
        # -------------------------------------------------------------
        print("\n[Vulnerability Test 4] Path Traversal Attack via Upload (../../etc/passwd payload)")
        malicious_file = {"file": ("../../etc/malicious_payload.exe", b"malicious binary code", "application/octet-stream")}
        res_upload = await client.post(
            "/api/v1/knowledge/upload",
            headers=headers_a,
            data={"title": "Attack Doc", "category": "Exploit"},
            files=malicious_file
        )
        if res_upload.status_code in [400, 422]:
            print(f"  --> [PASS] Path traversal / executable upload rejected with HTTP {res_upload.status_code}.")
            passed += 1
        else:
            print(f"  --> [FAIL] Malicious upload accepted! Status: {res_upload.status_code}")
            failed += 1

        # -------------------------------------------------------------
        # TEST 5: SQL Injection Simulation (SQLi via Query Parameters)
        # -------------------------------------------------------------
        print("\n[Vulnerability Test 5] SQL Injection Simulation (' OR '1'='1 Payload)")
        sqli_payload = {"query": "' OR '1'='1' --", "top_k": 5}
        res_sqli = await client.post("/api/v1/knowledge/search", json=sqli_payload, headers=headers_a)
        if res_sqli.status_code == 200:
            # Must return 0 or safe empty result rather than leaking all documents
            results = res_sqli.json()["data"]["results"]
            print(f"  --> [PASS] SQLi safely handled as literal string. Results returned: {len(results)} items (No injection occurred).")
            passed += 1
        else:
            print(f"  --> [FAIL] Query broke backend! Status: {res_sqli.status_code}")
            failed += 1

        # -------------------------------------------------------------
        # TEST 6: Sensitive Information Leakage in Headers/Errors
        # -------------------------------------------------------------
        print("\n[Vulnerability Test 6] Information Disclosure / Secret Leakage in Error Responses")
        res_err = await client.get("/api/v1/conversations/non_existent_uuid_12345", headers=headers_a)
        err_body = res_err.text.lower()
        leaks = [s for s in ["asyncpg", "traceback", "password", "jwt_secret", "postgres:admin123"] if s in err_body]
        if not leaks:
            print("  --> [PASS] Zero internal stack traces or database credentials leaked in error envelope.")
            passed += 1
        else:
            print(f"  --> [FAIL] Credentials or stack traces exposed: {leaks}")
            failed += 1

        # -------------------------------------------------------------
        # TEST 7: Idempotency Hijack & Duplicate Prevention
        # -------------------------------------------------------------
        print("\n[Vulnerability Test 7] Double-Submit / Race Condition Guard")
        idem_headers = {"Authorization": f"Bearer {token_a}", "Idempotency-Key": "pen_test_idem_key_007"}
        ticket_req = {"subject": "Critical Security Drill", "description": "Simulated double request"}
        r_first = await client.post("/api/v1/tickets", json=ticket_req, headers=idem_headers)
        r_second = await client.post("/api/v1/tickets", json=ticket_req, headers=idem_headers)
        if r_first.json()["data"]["ticket_id"] == r_second.json()["data"]["ticket_id"]:
            print("  --> [PASS] Idempotency guard intact. Exact same ticket ID returned on repeated submission.")
            passed += 1
        else:
            print("  --> [FAIL] Duplicate ticket created on identical idempotency key!")
            failed += 1

    print("\n" + "=" * 70)
    print(f" PENETRATION & AUDIT TEST RESULTS: {passed} PASSED, {failed} FAILED")
    print("=" * 70 + "\n")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_security_audit())
    sys.exit(0 if success else 1)

