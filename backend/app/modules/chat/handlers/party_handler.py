"""Parties Module Handler: Live Customer & Supplier Ledgers, Outstandings, and Contact Masters.

Provides SaaS production-grade natural language querying for party ledger balances,
GSTIN lookups, outstanding receivables/payables, and WhatsApp-ready party statements.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.modules.connector.client import connector_client


PARTY_STOP_WORDS = {
    "mera", "meri", "mere", "apna", "apni", "apne", "my", "the", "in", "ye", "yeh", "wo", "woh",
    "all", "sab", "sabhi", "pure", "dono", "har", "aaj", "kal", "today", "yesterday", "bank", "cash",
    "daybook", "reports", "report", "tally", "ctrlbooks", "company", "firm", "details", "detail",
    "balance", "closing", "opening", "outstanding", "hisab", "kitab", "kiska", "kis", "bhai", "please",
    "plz", "batao", "dikhao", "check", "karo", "status", "hai", "kya", "list", "total", "ka", "ki", "ke", "ko", "se"
}


def extract_party_search_term(query_text: str) -> Optional[str]:
    """Extracts a target party or customer candidate name from the user's message."""
    clean_text = query_text.strip()

    # Pattern A: <cand> party / customer / vendor / client / ledger [ka / ki / ke / balance ...]
    m_a = re.search(
        r"([A-Za-z0-9\s&.\'-]+?)\s+(?:party|customer|vendor|client|debtor|creditor|ledger)\b",
        clean_text,
        re.IGNORECASE,
    )
    if m_a:
        cand = m_a.group(1).strip()
        cand = re.sub(r"^(?:bhai|bro|please|plz|mera|mere|meri|apna|apne|apni|the|in|is|us|ye)\s+", "", cand, flags=re.IGNORECASE).strip()
        cand = re.sub(r"\s+(?:ka|ki|ke|ko|se)$", "", cand, flags=re.IGNORECASE).strip()
        if cand.lower() not in PARTY_STOP_WORDS and len(cand) >= 2:
            return cand

    # Pattern B: party / customer / vendor / ledger <cand> [ka / ki / ke / balance ...]
    m_b = re.search(
        r"(?:party|customer|vendor|client|debtor|creditor|khata|ledger)\s+(?:of|for|ka|ki|ke|ko|se)?\s*([A-Za-z0-9\s&.\'-]+?)(?:\s+(?:ka|ki|ke|ko|se|balance|details?|gstin|phone|address|hisab)\b|$)",
        clean_text,
        re.IGNORECASE,
    )
    if m_b:
        cand = m_b.group(1).strip()
        cand = re.sub(r"^(?:bhai|bro|please|plz|mera|mere|meri|apna|apne|apni|the|in|is|us|ye|of|for)\s+", "", cand, flags=re.IGNORECASE).strip()
        cand = re.sub(r"\s+(?:ka|ki|ke|ko|se)$", "", cand, flags=re.IGNORECASE).strip()
        if cand.lower() not in PARTY_STOP_WORDS and len(cand) >= 2:
            return cand

    # Pattern C: <cand> ka balance / ledger / details
    m_c = re.search(
        r"^([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|ko)\s+(?:balance|closing\s*balance|ledger|ledger\s*balance|outstanding|gstin|phone|address|number|hisab)\b",
        clean_text,
        re.IGNORECASE,
    )
    if m_c:
        cand = m_c.group(1).strip()
        cand = re.sub(r"^(?:bhai|bro|please|plz|mera|mere|apna|apne|is)\s+", "", cand, flags=re.IGNORECASE).strip()
        if cand.lower() not in PARTY_STOP_WORDS and len(cand) >= 2:
            return cand

    # Pattern D: "parties matching XYZ", "search party XYZ", "ledger of XYZ", "balance of XYZ"
    m_d = re.search(
        r"(?:matching|search|find|filter|ledger\s+of|details\s+of|balance\s+of)\s+([A-Za-z0-9\s&.\'-]+?)$",
        clean_text,
        re.IGNORECASE,
    )
    if m_d:
        cand = m_d.group(1).strip()
        if cand.lower() not in PARTY_STOP_WORDS and len(cand) >= 2:
            return cand

    return None


async def handle_parties(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    lang_code: str,
    is_ticket_intent: bool,
    is_voucher_intent: bool,
    is_cash_bank_intent: bool,
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles Party / Customer / Vendor inquiries (balances, outstandings, GSTIN, contacts)."""
    if is_ticket_intent or is_voucher_intent or is_cash_bank_intent:
        return False, [], "", None

    # Guard against explicit voucher creation
    is_voucher_action = bool(
        re.search(
            r"\b(banao|create|entry|generate|add|katna|bana\s*do|kaat\s*do|post|karo)\b",
            last_msg_lower,
            re.IGNORECASE,
        )
    ) and bool(re.search(r"\b(invoice|bill|voucher|sales|receipt|payment)\b", last_msg_lower))
    if is_voucher_action:
        return False, [], "", None

    # Check for Party / Customer / Vendor / Ledger intent
    has_party_kw = bool(
        re.search(
            r"\b(part(?:y|ies)|customers?|vendors?|suppliers?|debtors?|creditors?|sundry\s*debtors?|sundry\s*creditors?|clients?|khata|khate|ledgers?)\b|"
            r"(?:पार्टी|पार्टियां|ग्राहक|सप्लायर|कस्टमर|खाता|लेजर|लेज़र)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    has_outstanding_kw = bool(
        re.search(
            r"\b(outstanding|lena\s+hai|dena\s+hai|baki\s+hai|pending\s+payment|payment\s+aana|kisko\s+dena|kisse\s+lena)\b|"
            r"(?:बाकी|लेना\s*है|देना\s*है)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    party_search_cand = extract_party_search_term(last_user_message)

    is_party_inquiry = has_party_kw or has_outstanding_kw or (party_search_cand is not None and "balance" in last_msg_lower)

    if not is_party_inquiry:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    # Resolve target company
    effective_company = active_company
    effective_company_id = caller.get("company_id")

    if effective_company.lower() in ("ctrlbooks", "your company", "active company", "default", ""):
        try:
            comp_details = await connector_client.resolve_company_details(token=caller.get("connector_token"))
            effective_company = comp_details.get("company_name", effective_company)
            effective_company_id = comp_details.get("company_id", effective_company_id)
        except Exception:
            pass

    token = caller.get("connector_token")

    # Call get_company_ledgers (comprehensive Tally ledgers) or get_company_parties
    items: List[Dict[str, Any]] = []
    tot_count = 0
    tot_debit = 0.0
    tot_credit = 0.0

    try:
        # First query full /ledgers endpoint (covers 100% of Tally ledgers)
        ledgers_res = await connector_client.get_company_ledgers(
            company_name=effective_company,
            company_id=effective_company_id,
            page=1,
            limit=20,
            q=party_search_cand,
            token=token,
        )
        if ledgers_res.get("success") and ledgers_res.get("items"):
            items = ledgers_res["items"]
            tot_count = int(ledgers_res.get("total") or len(items))
            tot_debit = float(ledgers_res.get("total_debit") or 0.0)
            tot_credit = float(ledgers_res.get("total_credit") or 0.0)
            if not effective_company_id and ledgers_res.get("company_id"):
                effective_company_id = ledgers_res["company_id"]
        else:
            # Fallback to get_company_parties
            parties_res = await connector_client.get_company_parties(
                company_name=effective_company,
                company_id=effective_company_id,
                page=1,
                limit=20,
                q=party_search_cand,
                token=token,
            )
            items = parties_res.get("items") or []
            tot_count = int(parties_res.get("total") or len(items))
            tot_debit = float(parties_res.get("total_debit") or 0.0)
            tot_credit = float(parties_res.get("total_credit") or 0.0)
            if not effective_company_id and parties_res.get("company_id"):
                effective_company_id = parties_res["company_id"]
    except Exception as e:
        items = []
        tot_count = 0
        tot_debit = 0.0
        tot_credit = 0.0


    result_data = {
        "success": True,
        "company_name": effective_company,
        "company_id": effective_company_id or "",
        "search_query": party_search_cand,
        "total": tot_count,
        "page": 1,
        "limit": 20,
        "total_debit": round(tot_debit, 2),
        "total_credit": round(tot_credit, 2),
        "net_balance": round(tot_debit - tot_credit, 2),
        "items": items,
    }

    executed_tools.append({"tool": "get_parties_command", "result": result_data})
    tool_results_text = (
        f"\n[Parties & Ledgers]: Search='{party_search_cand or 'All'}', Company={effective_company}, "
        f"Count={len(items)}/{tot_count}, TotalReceivable(Dr)=₹{tot_debit:,.2f}, TotalPayable(Cr)=₹{tot_credit:,.2f}"
    )

    def _fmt_party_bal(val: float, lang: str = "en") -> str:
        abs_str = f"₹{abs(val):,.2f}"
        if val > 0:
            if lang == "hi":
                return f"{abs_str} (डेबिट / लेना है - Dr)"
            return f"{abs_str} (Dr - Receivable)"
        elif val < 0:
            if lang == "hi":
                return f"{abs_str} (क्रेडिट / देना है/एडवांस - Cr)"
            return f"{abs_str} (Cr - Payable/Advance)"
        return "₹0.00 (Settled)"

    # Format natural response
    if party_search_cand and len(items) == 1:
        # Single exact party / ledger result
        p = items[0]
        p_name = p.get("name") or p.get("partyName", "Party / Ledger")
        p_group = p.get("group") or p.get("parent") or ""
        p_bal = float(p.get("closingBalance") or 0.0)
        p_gstin = p.get("gstin") or ""
        p_phone = p.get("phone") or "N/A"
        p_addr = p.get("address") or ""
        p_last_sold = p.get("lastSoldDate")
        if p_last_sold and "T" in str(p_last_sold):
            p_last_sold = str(p_last_sold).split("T")[0]

        grp_line_en = f"• **Under Group:** {p_group}\n" if p_group and p_group != "Primary" else ""
        grp_line_hi = f"• **ग्रुप / श्रेणी:** {p_group}\n" if p_group and p_group != "Primary" else ""
        grp_line_hg = f"• **Under Group:** {p_group}\n" if p_group and p_group != "Primary" else ""

        if lang_code == "en-IN":
            slot_missing_reply = (
                f"👤 **{p_name} — Ledger Statement:**\n\n"
                f"{grp_line_en}"
                f"• **Closing Balance:** **{_fmt_party_bal(p_bal, lang='en')}**\n"
            )
            if p_gstin and p_gstin != "Not Registered":
                slot_missing_reply += f"• **GSTIN:** `{p_gstin}`\n"
            if p_phone and p_phone != "N/A":
                slot_missing_reply += f"• **Phone:** {p_phone}\n"
            if p_last_sold and p_last_sold != "N/A":
                slot_missing_reply += f"• **Last Transaction Date:** {p_last_sold}\n"
            slot_missing_reply += "\nThe interactive Ledger Card is loaded below with 1-click WhatsApp sharing!"

        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"👤 **{p_name} — लेजर / खाता विवरण:**\n\n"
                f"{grp_line_hi}"
                f"• **क्लोजिंग बैलेंस:** **{_fmt_party_bal(p_bal, lang='hi')}**\n"
            )
            if p_gstin and p_gstin != "Not Registered":
                slot_missing_reply += f"• **जीएसटीआईएन (GSTIN):** `{p_gstin}`\n"
            if p_phone and p_phone != "N/A":
                slot_missing_reply += f"• **फोन:** {p_phone}\n"
            if p_last_sold and p_last_sold != "N/A":
                slot_missing_reply += f"• **अंतिम लेनदेन दिनांक:** {p_last_sold}\n"
            slot_missing_reply += "\nनीचे लेजर का लाइव कार्ड लोड कर दिया गया है। आप इसे सीधे व्हाट्सएप पर शेयर कर सकते हैं!"

        else:  # Hinglish / Default
            slot_missing_reply = (
                f"👤 **{p_name}** ka **Ledger Balance**:\n\n"
                f"{grp_line_hg}"
                f"• **Closing Balance:** **{_fmt_party_bal(p_bal, lang='en')}**\n"
            )
            if p_gstin and p_gstin != "Not Registered":
                slot_missing_reply += f"• **GSTIN:** `{p_gstin}`\n"
            if p_phone and p_phone != "N/A":
                slot_missing_reply += f"• **Phone:** {p_phone}\n"
            if p_last_sold and p_last_sold != "N/A":
                slot_missing_reply += f"• **Last Transaction Date:** {p_last_sold}\n"
            slot_missing_reply += "\nInteractive Ledger Card niche ready hai, jise aap direct WhatsApp par party ko share kar sakte hain!"

    elif len(items) > 0:
        # Multiple ledgers / parties list
        top_lines = ""
        for it in items[:5]:
            nm = it.get("name") or it.get("partyName", "Ledger")
            grp = it.get("group") or it.get("parent") or ""
            grp_str = f" ({grp})" if grp and grp != "Primary" else ""
            b_val = float(it.get("closingBalance") or 0.0)
            top_lines += f"  • **{nm}**{grp_str}: {_fmt_party_bal(b_val, lang='en')}\n"

        search_note_en = f" matching '{party_search_cand}'" if party_search_cand else ""
        search_note_hi = f" ('{party_search_cand}' अनुसार)" if party_search_cand else ""
        search_note_hg = f" ('{party_search_cand}' search ke sath)" if party_search_cand else ""

        if lang_code == "en-IN":
            slot_missing_reply = (
                f"👥 **{effective_company} — Ledgers & Accounts Overview{search_note_en}:**\n\n"
                f"• **Total Active Ledgers in Tally:** **{tot_count}**\n"
                f"• **Total Debit Balance (Dr):** **₹{tot_debit:,.2f}**\n"
                f"• **Total Credit Balance (Cr):** **₹{tot_credit:,.2f}**\n\n"
                f"**Key Ledgers Breakdown:**\n{top_lines}\n"
                "Interactive Ledger Directory Card is loaded below!"
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"👥 **{effective_company} — लेजर एवं खाता विवरण{search_note_hi}:**\n\n"
                f"• **कुल लेजर्स (Tally):** **{tot_count}**\n"
                f"• **कुल डेबिट राशि (Dr):** **₹{tot_debit:,.2f}**\n"
                f"• **कुल क्रेडिट राशि (Cr):** **₹{tot_credit:,.2f}**\n\n"
                f"**प्रमुख लेजर्स:**\n{top_lines}\n"
                "नीचे लेजर डायरेक्टरी कार्ड लोड कर दिया गया है!"
            )
        else:  # Hinglish
            slot_missing_reply = (
                f"👥 **{effective_company}** ki **Ledgers & Accounts Summary{search_note_hg}**:\n\n"
                f"• **Kul Ledgers in Tally:** **{tot_count}**\n"
                f"• **Total Debit Balance (Dr):** **₹{tot_debit:,.2f}**\n"
                f"• **Total Credit Balance (Cr):** **₹{tot_credit:,.2f}**\n\n"
                f"**Top Ledgers:**\n{top_lines}\n"
                "Aapke liye interactive Ledger Directory card niche live ho chuka hai!"
            )


    else:
        # 0 parties found
        cand_str = f"'{party_search_cand}'" if party_search_cand else "diye gaye filter"
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"ℹ️ No party matching {cand_str} was found in **{effective_company}**.\n\n"
                "Would you like to search with a different party name or create a new customer ledger?"
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"ℹ️ **{effective_company}** में {cand_str} नाम से कोई पार्टी नहीं मिली।\n\n"
                "क्या आप किसी अन्य नाम से खोजना चाहते हैं?"
            )
        else:
            slot_missing_reply = (
                f"ℹ️ **{effective_company}** me {cand_str} naam se koi party ledger nahi mila.\n\n"
                "Aap koi doosra naam search karna chahenge?"
            )

    return True, executed_tools, tool_results_text, slot_missing_reply
