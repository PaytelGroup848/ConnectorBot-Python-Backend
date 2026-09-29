"""Voucher Handler: Slot filling and creation for Sales, Receipt, Payment, Purchase, Notes, Contra, Journal."""

import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from app.middleware.tenant_context import TenantContext
from app.modules.connector.client import connector_client
from app.modules.connector.tools import execute_tool


async def handle_voucher_creation(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    ctx: TenantContext,
    lang_code: str,
    lang_name: str,
    sample_party: str,
    today_date: str,
    is_ticket_intent: bool,
    extract_entities_fn: Callable[[str], Dict[str, Any]],
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles voucher intent, slot-filling prompts, and execution for Sales, Receipt, Payment, etc."""
    is_voucher_intent = (not is_ticket_intent) and bool(
        re.search(
            r"(voucher|invoice|bill|receipt|entry|इनवॉइस|बिल|वाउचर|रसीद|બિલ|इन्व्हॉइस).*?(bna|bana|create|generate|daal|karo|kaat|kat|make|new|बना|बनवा|બનાવો)|(bna|bana|create|generate|daal|karo|make|new|बना|बनवा|બનાવો).*?(voucher|invoice|bill|receipt|entry|इनवॉइस|बिल|वाउचर|रसीद|બિલ|इन्व्हॉइस)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    if not is_voucher_intent:
        return False, [], "", None

    extracted = extract_entities_fn(last_user_message)
    if not extracted:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    amt = extracted.get("amount")
    party = extracted.get("party")
    v_type = extracted.get("voucher_type", "Sales")
    gst_rate = extracted.get("gst_rate", 18.0)
    is_igst = extracted.get("is_igst", False)

    if not party and amt:
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"I am ready to generate a **{v_type} Voucher** for **₹{amt:,.2f}**!\n\n"
                f"Please provide the **Customer / Party Name** (e.g., *'{sample_party}'*)."
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"मैं **₹{amt:,.2f}** का **{v_type} वाउचर** बनाने के लिए तैयार हूँ!\n\n"
                f"कृपया **पार्टी / ग्राहक का नाम** बताएं (जैसे: *'{sample_party}'*)."
            )
        else:
            slot_missing_reply = (
                f"Main **₹{amt:,.2f}** ka **{v_type} Voucher** create karne ke liye ready hoon!\n\n"
                f"Kripya **Customer / Party Name** batayein (Jaise: *'{sample_party}'*)."
            )
        return True, executed_tools, tool_results_text, slot_missing_reply

    elif not amt and party:
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"I am ready to create a **{v_type} Voucher** for **{party}**!\n\n"
                f"Please specify the **Voucher Amount**."
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"मैं **{party}** के लिए **{v_type} वाउचर** बनाने के लिए तैयार हूँ!\n\n"
                f"कृपया **राशि (Amount)** बताएं।"
            )
        else:
            slot_missing_reply = (
                f"Main **{party}** ke liye **{v_type} Voucher** create karne ke liye ready hoon!\n\n"
                f"Kripya **Amount** batayein."
            )
        return True, executed_tools, tool_results_text, slot_missing_reply

    elif not party and not amt:
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"To create a **{v_type} Voucher** in **{active_company}**, please specify the **Party Name** and **Amount**.\n\n"
                f"Example: *'Create a sales invoice for {sample_party} of ₹25,000'*"
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"**{active_company}** में वाउचर बनाने के लिए कृपया **पार्टी का नाम** और **राशि (Amount)** बताएं।\n\n"
                f"उदाहरण: *'{sample_party} के लिए 25,000 का सेल्स इनवॉइस बना दो'*"
            )
        else:
            slot_missing_reply = (
                f"**{active_company}** me Voucher create karne ke liye kripya **Party Name** aur **Amount** batayein.\n\n"
                f"Format: *'{sample_party} ke liye 25,000 ka sales invoice bana do'*"
            )
        return True, executed_tools, tool_results_text, slot_missing_reply

    # Both party and amt are present -> dispatch command
    target_comp_name = extracted.get("target_company")
    effective_company = active_company
    effective_company_id = caller.get("company_id")

    if target_comp_name:
        comp_details = await connector_client.resolve_company_details(
            company_name=target_comp_name,
            token=caller.get("connector_token"),
        )
        if comp_details.get("company_id"):
            effective_company = comp_details.get("company_name", target_comp_name)
            effective_company_id = comp_details["company_id"]
    elif effective_company.lower() in ("ctrlbooks", "your company", "active company", "default", ""):
        try:
            comp_details = await connector_client.resolve_company_details(token=caller.get("connector_token"))
            effective_company = comp_details.get("company_name", effective_company)
            effective_company_id = comp_details.get("company_id", effective_company_id)
        except Exception:
            pass

    common_kw = {
        "company_name": effective_company,
        "company_id": effective_company_id,
        "connector_token": caller.get("connector_token"),
        "tally_port": caller.get("tally_port"),
    }

    if v_type == "Receipt":
        voucher_data = await execute_tool(
            "create_receipt_voucher_command",
            {
                **common_kw,
                "party_ledger": party,
                "bank_or_cash_ledger": "Bank Account",
                "amount": amt,
                "date": today_date,
            },
            ctx,
        )
        executed_tools.append({"tool": "create_receipt_voucher_command", "result": voucher_data})
    elif v_type == "Payment":
        voucher_data = await execute_tool(
            "create_payment_voucher_command",
            {
                **common_kw,
                "party_ledger": party,
                "bank_or_cash_ledger": "Bank Account",
                "amount": amt,
                "date": today_date,
            },
            ctx,
        )
        executed_tools.append({"tool": "create_payment_voucher_command", "result": voucher_data})
    elif v_type == "Purchase":
        voucher_data = await execute_tool(
            "create_purchase_invoice_command",
            {
                **common_kw,
                "party_ledger": party,
                "date": today_date,
                "total_amount": amt,
                "gst_rate": gst_rate,
                "items": [{"itemName": f"Material from {party}", "quantity": 1, "rate": amt, "amount": amt}],
            },
            ctx,
        )
        executed_tools.append({"tool": "create_purchase_invoice_command", "result": voucher_data})
    elif v_type == "Credit Note":
        voucher_data = await execute_tool(
            "create_credit_note_command",
            {
                **common_kw,
                "party_ledger": party,
                "amount": amt,
                "date": today_date,
                "reason": "Sales Return",
            },
            ctx,
        )
        executed_tools.append({"tool": "create_credit_note_command", "result": voucher_data})
    elif v_type == "Debit Note":
        voucher_data = await execute_tool(
            "create_debit_note_command",
            {
                **common_kw,
                "party_ledger": party,
                "amount": amt,
                "date": today_date,
                "reason": "Purchase Return",
            },
            ctx,
        )
        executed_tools.append({"tool": "create_debit_note_command", "result": voucher_data})
    elif v_type == "Contra":
        voucher_data = await execute_tool(
            "create_contra_command",
            {
                **common_kw,
                "from_account": "Cash",
                "to_account": "Bank Account",
                "amount": amt,
                "date": today_date,
            },
            ctx,
        )
        executed_tools.append({"tool": "create_contra_command", "result": voucher_data})
    elif v_type == "Journal":
        voucher_data = await execute_tool(
            "create_journal_command",
            {
                **common_kw,
                "amount": amt,
                "date": today_date,
                "narration": f"Journal entry for {party or 'General'}",
            },
            ctx,
        )
        executed_tools.append({"tool": "create_journal_command", "result": voucher_data})
    else:
        voucher_data = await execute_tool(
            "create_sales_invoice_command",
            {
                **common_kw,
                "party_ledger": party,
                "date": today_date,
                "total_amount": amt,
                "gst_rate": gst_rate,
                "is_igst": is_igst,
                "narration": f"AI Multilingual {v_type} Voucher ({lang_name})",
                "items": [{"name": f"{v_type} - {party}", "itemName": f"{v_type} - {party}", "quantity": 1, "rate": amt, "units": "NOS", "amount": amt}],
            },
            ctx,
        )
        executed_tools.append({"tool": "create_sales_invoice_command", "result": voucher_data})

    tool_results_text = f"\n[Voucher Queued]: Type={v_type}, ID={voucher_data.get('voucher_number')}, Company={effective_company}, Party={party}, Amount={amt}"
    return True, executed_tools, tool_results_text, None
