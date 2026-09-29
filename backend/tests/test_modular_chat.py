"""Comprehensive Unit & Regression Tests for Modular Chat Handlers and AIGateway."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.middleware.tenant_context import TenantContext
from app.modules.chat.ai_gateway import (
    AIGateway,
    normalize_indian_numerals,
    detect_language_and_script,
    extract_voucher_entities,
)
from app.modules.chat.handlers.reports_handler import handle_accounting_reports
from app.modules.chat.handlers.sales_handler import handle_sales_analytics, handle_voucher_lookup
from app.modules.chat.handlers.voucher_handler import handle_voucher_creation
from app.modules.chat.handlers.ticket_handler import handle_ticket_status_check, handle_ticket_creation


async def run_modular_chat_tests():
    print("\n" + "=" * 60)
    print(" TESTING MODULAR REFACTORED CHAT ARCHITECTURE")
    print("=" * 60)

    # 1. Test Indian Numerals & LID
    norm = normalize_indian_numerals("bhai 50 hazar ka sales invoice bna do")
    assert "50000" in norm
    lid = detect_language_and_script("aaj ka report dikhao")
    assert lid["code"] == "hinglish"
    lid_hi = detect_language_and_script("आज का रिपोर्ट दिखाओ")
    assert lid_hi["code"] == "hi-IN"
    print("  [PASS] 1. Regional Indian Numerals & Auto-LID verified")

    # 2. Test Accounting Reports Handler
    caller = {
        "name": "Test User",
        "email": "test@example.com",
        "phone": "9876543210",
        "tally_port": 9000,
        "company_id": "test-comp-123",
        "connector_token": "mock-token",
    }

    handled, tools, tool_text, reply = await handle_accounting_reports(
        last_user_message="mere aaj ka reports do",
        last_msg_lower="mere aaj ka reports do",
        caller=caller,
        active_company="CtrlBooks",
        lang_code="hinglish",
        is_ticket_intent=False,
        is_voucher_intent=False,
    )
    assert handled is True
    assert len(tools) > 0
    assert tools[0]["tool"] == "get_accounting_report_command"
    assert reply is not None
    print("  [PASS] 2. Reports Handler (Day Book / Reports) verified")

    # 3. Test Trial Balance & P&L in Reports Handler
    handled_tb, tools_tb, _, reply_tb = await handle_accounting_reports(
        last_user_message="trial balance dikhao",
        last_msg_lower="trial balance dikhao",
        caller=caller,
        active_company="CtrlBooks",
        lang_code="en-IN",
        is_ticket_intent=False,
        is_voucher_intent=False,
    )
    assert handled_tb is True
    assert tools_tb[0]["result"]["report_type"] == "trial-balance"
    print("  [PASS] 3. Reports Handler (Trial Balance) verified")

    # 4. Test Sales Analytics Handler
    handled_s, tools_s, _, reply_s = await handle_sales_analytics(
        last_user_message="aaj ka sales batao",
        last_msg_lower="aaj ka sales batao",
        caller=caller,
        active_company="CtrlBooks",
        lang_code="hinglish",
        sample_party="Acme Corp",
        is_ticket_intent=False,
        is_voucher_intent=False,
        is_accounting_reports_intent=False,
    )
    assert handled_s is True
    assert tools_s[0]["tool"] == "get_sales_analytics_command"
    print("  [PASS] 4. Sales Analytics Handler verified")

    # 5. Test Voucher Creation Slot Filling
    ctx = TenantContext(tenant_id="tenant-1", user_id="user-1", role="admin")
    handled_v, tools_v, _, reply_v = await handle_voucher_creation(
        last_user_message="sales invoice bana do 25000 ka",
        last_msg_lower="sales invoice bana do 25000 ka",
        caller=caller,
        active_company="CtrlBooks",
        ctx=ctx,
        lang_code="hinglish",
        lang_name="Hinglish",
        sample_party="Acme Traders",
        today_date="2026-09-29",
        is_ticket_intent=False,
        extract_entities_fn=extract_voucher_entities,
    )
    assert handled_v is True
    assert reply_v is not None  # party missing prompt
    assert "Customer / Party Name" in reply_v
    print("  [PASS] 5. Voucher Slot Filling Handler verified")

    # 6. Test AIGateway Full Orchestration
    gateway = AIGateway()
    res = await gateway.generate_response(
        messages=[{"role": "user", "content": "aaj ka day book dikhao"}],
        ctx=ctx,
        company_name="CtrlBooks",
        user_meta=caller,
    )
    assert "content" in res
    assert len(res["tool_calls"]) > 0
    assert res["detected_language"] in ("Hinglish", "Hindi", "English")
    print("  [PASS] 6. AIGateway Full Orchestration with Modular Handlers verified")

    print("=" * 60)
    print(" ALL MODULAR REFACTORING UNIT TESTS PASSED SUCCESSFULLY!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_modular_chat_tests())
