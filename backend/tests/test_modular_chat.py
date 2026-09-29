"""Comprehensive Unit & Regression Tests for Modular Chat Handlers and AIGateway."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.middleware.tenant_context import TenantContext
from app.core.config import settings
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
        "company_id": "6aa0f659f858467a84d08d57",
        "connector_token": getattr(settings, "CONNECTOR_API_TOKEN", "") or "mock-token",
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

    # 6. Test Cash & Bank Module Handler
    from app.modules.chat.handlers.cash_bank_handler import handle_cash_bank
    handled_cb, tools_cb, _, reply_cb = await handle_cash_bank(
        last_user_message="mera cash kitna hai",
        last_msg_lower="mera cash kitna hai",
        caller=caller,
        active_company="CtrlBooks",
        lang_code="hinglish",
        is_ticket_intent=False,
        is_voucher_intent=False,
    )
    assert handled_cb is True
    assert tools_cb[0]["tool"] == "get_cash_bank_command"
    assert tools_cb[0]["result"]["module"] == "cash"
    print("  [PASS] 6. Cash Module Handler verified")

    handled_bank, tools_bank, _, reply_bank = await handle_cash_bank(
        last_user_message="HDFC bank ka balance batao",
        last_msg_lower="hdfc bank ka balance batao",
        caller=caller,
        active_company="CtrlBooks",
        lang_code="en-IN",
        is_ticket_intent=False,
        is_voucher_intent=False,
    )
    assert handled_bank is True
    assert tools_bank[0]["result"]["search_query"] == "HDFC"
    assert tools_bank[0]["result"]["module"] == "bank"
    print("  [PASS] 7. Bank Search Filter (q=HDFC) verified")

    handled_both, tools_both, _, reply_both = await handle_cash_bank(
        last_user_message="cash aur bank dono dikhao",
        last_msg_lower="cash aur bank dono dikhao",
        caller=caller,
        active_company="CtrlBooks",
        lang_code="hinglish",
        is_ticket_intent=False,
        is_voucher_intent=False,
    )
    assert handled_both is True
    assert tools_both[0]["result"]["module"] == "both"
    print("  [PASS] 8. Combined Cash & Bank (Liquid Funds) verified")

    # 9. Test AIGateway Full Orchestration
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
    print("  [PASS] 9. AIGateway Full Orchestration with Modular Handlers verified")

    # 10. Test AIGateway Cash & Bank Query
    res_cb = await gateway.generate_response(
        messages=[{"role": "user", "content": "mera cash kitna hai"}],
        ctx=ctx,
        company_name="CtrlBooks",
        user_meta=caller,
    )
    assert any(t["tool"] == "get_cash_bank_command" for t in res_cb.get("tool_calls", []))
    print("  [PASS] 10. AIGateway Cash & Bank Intent Routing verified")

    # 11. Test Parties Module Handler (Single Party Lookup)
    from app.modules.chat.handlers.party_handler import handle_parties
    handled_p, tools_p, _, reply_p = await handle_parties(
        last_user_message="20 Microns Limited party ka balance kitna hai?",
        last_msg_lower="20 microns limited party ka balance kitna hai?",
        caller=caller,
        active_company="Annai Agency - 2022-2023",
        lang_code="hinglish",
        is_ticket_intent=False,
        is_voucher_intent=False,
        is_cash_bank_intent=False,
    )
    assert handled_p is True
    assert tools_p[0]["tool"] == "get_parties_command"
    assert tools_p[0]["result"]["search_query"] == "20 Microns Limited"
    print("  [PASS] 11. Parties Handler (Single Party Search) verified")

    # 12. Test AIGateway Parties Query Orchestration
    res_p = await gateway.generate_response(
        messages=[{"role": "user", "content": "meri parties dikhao"}],
        ctx=ctx,
        company_name="Annai Agency - 2022-2023",
        user_meta=caller,
    )
    assert any(t["tool"] == "get_parties_command" for t in res_p.get("tool_calls", []))
    print("  [PASS] 12. AIGateway Parties Intent Routing verified")

    print("=" * 60)
    print(" ALL MODULAR REFACTORING, CASH/BANK & PARTIES TESTS PASSED SUCCESSFULLY!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_modular_chat_tests())
