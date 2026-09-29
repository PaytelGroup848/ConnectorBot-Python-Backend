"""Cash & Bank Module Handler: Live Cash in Hand, Bank Accounts, and Liquid Funds.

Provides SaaS production-grade natural language querying, multi-bank aggregation,
search filters (e.g. q=HDFC), and corporate WhatsApp-ready summaries.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.modules.connector.client import connector_client


KNOWN_BANK_KEYWORDS = [
    "hdfc", "sbi", "icici", "axis", "kotak", "pnb", "bob", "canara",
    "union", "yes", "indusind", "idbi", "federal", "standard chartered",
    "hsbc", "citi", "rbl", "bandhan", "central", "indian"
]


STOP_WORDS_BEFORE_BANK = {
    "mera", "meri", "mere", "apna", "apni", "apne", "my", "the", "in", "ye", "yeh", "wo", "woh",
    "all", "har", "aur", "and", "or", "ka", "ki", "ke", "me", "mein", "mai", "se", "to", "bhi",
    "kisi", "koi", "is", "us", "sab", "sabhi", "pure", "dono", "cash", "nakad", "rokad", "tally"
}


def extract_bank_search_term(query_text: str) -> Optional[str]:
    """Extracts target bank search keyword like HDFC, SBI, ICICI from the user's message."""
    lower = query_text.lower()
    for kw in KNOWN_BANK_KEYWORDS:
        if re.search(rf"\b{kw}\b", lower):
            return kw.upper()

    # Generic extraction e.g. "XYZ bank"
    m = re.search(r"\b([A-Za-z0-9\-]+)\s+bank\b", query_text, re.IGNORECASE)
    if m:
        cand = m.group(1).strip()
        if cand.lower() not in STOP_WORDS_BEFORE_BANK and len(cand) >= 2:
            return cand.upper()
    return None


async def handle_cash_bank(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    lang_code: str,
    is_ticket_intent: bool,
    is_voucher_intent: bool,
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles Cash and Bank balance inquiries (Cash in hand, Bank accounts, Liquid Funds)."""
    # 1. Guard against voucher creation or ticketing actions
    if is_ticket_intent or is_voucher_intent:
        return False, [], "", None

    is_voucher_action = bool(
        re.search(
            r"\b(banao|create|entry|generate|add|katna|bana\s*do|kaat\s*do|post|karo)\b",
            last_msg_lower,
            re.IGNORECASE,
        )
    )
    if is_voucher_action:
        return False, [], "", None

    # 2. Check for Cash / Bank intent patterns
    has_cash_kw = bool(
        re.search(
            r"\b(cash|nakad|petty\s*cash|cash\s*in\s*hand|cash\s*balance|cash\s*account|rokad)\b|"
            r"(?:कैश|रोकड़|नकद)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    has_bank_kw = bool(
        re.search(
            r"\b(bank|banks|bank\s*balance|bank\s*account|bank\s*accounts|bank\s*me|bank\s*mai|khata|khate)\b|"
            r"(?:बैंक|बैंक\s*बैलेंस|खाता|खाते)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    bank_search_term = extract_bank_search_term(last_user_message)
    if bank_search_term:
        has_bank_kw = True

    has_balance_inquiry = bool(
        re.search(
            r"\b(kitna|kitne|batao|dikhao|status|check|balance|summary|total|position|kya\s+hai|details?|hai\s+kya)\b|"
            r"(?:कितना|बताओ|दिखाओ|बैलेंस|स्थिति)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    has_liquidity_kw = bool(
        re.search(
            r"\b(liquid\s*funds?|liquidity|cash\s*(?:and|aur|&|\+)\s*bank|bank\s*(?:and|aur|&|\+)\s*cash|paise\s*kitne|paisa\s*kitna)\b|"
            r"(?:कैश\s*और\s*बैंक|लिक्विड)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    # Must have Cash or Bank keyword or explicit liquidity inquiry
    is_cash_bank_query = (has_cash_kw or has_bank_kw or has_liquidity_kw) and (
        has_balance_inquiry or has_liquidity_kw or bank_search_term is not None or "balance" in last_msg_lower
    )

    if not is_cash_bank_query:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    # Resolve target company
    effective_company = active_company
    effective_company_id = caller.get("company_id")

    comp_patterns = [
        r"^(?:in\s+)?(.*?)\s+(?:me|mein|में)\s+",
        r"(?:company\s+|कंपनी\s+)?([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|company\s+ka)\s+(?:cash|bank|balance)",
    ]
    for pat in comp_patterns:
        m_c = re.search(pat, last_user_message, re.IGNORECASE)
        if m_c:
            c_cand = m_c.group(1).strip()
            c_cand = re.sub(r"^(?:mere|apne|my|the|in|mujhe|is)\s+", "", c_cand, flags=re.IGNORECASE).strip()
            if len(c_cand) >= 3 and c_cand.lower() not in {"cash", "bank", "balance", "tally", "ctrlbooks"}:
                comp_details = await connector_client.resolve_company_details(
                    company_name=c_cand,
                    token=caller.get("connector_token"),
                )
                if comp_details.get("company_id"):
                    effective_company = comp_details.get("company_name", c_cand)
                    effective_company_id = comp_details["company_id"]
                    break

    if effective_company.lower() in ("ctrlbooks", "your company", "active company", "default", ""):
        try:
            comp_details = await connector_client.resolve_company_details(token=caller.get("connector_token"))
            effective_company = comp_details.get("company_name", effective_company)
            effective_company_id = comp_details.get("company_id", effective_company_id)
        except Exception:
            pass

    # Determine query mode: cash, bank, or both
    if has_cash_kw and not has_bank_kw and not has_liquidity_kw:
        target_mode = "cash"
    elif has_bank_kw and not has_cash_kw and not has_liquidity_kw:
        target_mode = "bank"
    else:
        target_mode = "both"

    token = caller.get("connector_token")
    cash_items: List[Dict[str, Any]] = []
    bank_items: List[Dict[str, Any]] = []
    tot_cash = 0.0
    tot_bank = 0.0

    if target_mode in ("cash", "both"):
        try:
            cash_res = await connector_client.get_company_cash(
                company_name=effective_company,
                company_id=effective_company_id,
                page=1,
                limit=10,
                token=token,
            )
            if cash_res.get("success"):
                cash_items = cash_res.get("items") or []
                tot_cash = float(cash_res.get("total_amount") or 0.0)
                if not effective_company_id and cash_res.get("company_id"):
                    effective_company_id = cash_res["company_id"]
        except Exception:
            pass

    if target_mode in ("bank", "both"):
        try:
            bank_res = await connector_client.get_company_bank(
                company_name=effective_company,
                company_id=effective_company_id,
                page=1,
                limit=10,
                q=bank_search_term,
                token=token,
            )
            if bank_res.get("success"):
                bank_items = bank_res.get("items") or []
                tot_bank = float(bank_res.get("total_amount") or 0.0)
                if not effective_company_id and bank_res.get("company_id"):
                    effective_company_id = bank_res["company_id"]
        except Exception:
            pass

    tot_liquid = tot_cash + tot_bank

    result_data = {
        "success": True,
        "module": target_mode,
        "company_name": effective_company,
        "company_id": effective_company_id or "",
        "search_query": bank_search_term,
        "cash_accounts": cash_items,
        "bank_accounts": bank_items,
        "total_cash": round(tot_cash, 2),
        "total_bank": round(tot_bank, 2),
        "total_liquid": round(tot_liquid, 2),
        "page": 1,
        "limit": 10,
    }

    executed_tools.append({"tool": "get_cash_bank_command", "result": result_data})
    tool_results_text = (
        f"\n[Cash & Bank Position]: Module={target_mode}, Company={effective_company}, "
        f"Cash=₹{tot_cash:,.2f}, Bank=₹{tot_bank:,.2f}, TotalLiquid=₹{tot_liquid:,.2f}"
    )

    def _fmt_dr_cr(val: float, is_bank: bool = False, lang: str = "en") -> str:
        abs_str = f"₹{abs(val):,.2f}"
        if val < 0:
            if lang == "hi":
                return f"{abs_str} (ओवरड्राफ्ट / OD)" if is_bank else f"{abs_str} (क्रेडिट / Cr)"
            return f"{abs_str} (OD / Cr)" if is_bank else f"{abs_str} (Cr)"
        if lang == "hi":
            return f"{abs_str} (जमा / Dr)"
        return f"{abs_str} (Dr)"

    # Format natural language executive response
    bank_lines_en = ""
    bank_lines_hi = ""
    bank_lines_hinglish = ""
    for b in bank_items[:4]:
        b_name = b.get("name", "Bank")
        b_bal = float(b.get("closingBalance") or 0.0)
        bank_lines_en += f"  • **{b_name}**: {_fmt_dr_cr(b_bal, is_bank=True, lang='en')}\n"
        bank_lines_hi += f"  • **{b_name}**: {_fmt_dr_cr(b_bal, is_bank=True, lang='hi')}\n"
        bank_lines_hinglish += f"  • **{b_name}**: {_fmt_dr_cr(b_bal, is_bank=True, lang='en')}\n"

    filter_notice_en = f" (filtered by '{bank_search_term}')" if bank_search_term else ""
    filter_notice_hi = f" ('{bank_search_term}' फ़िल्टर अनुसार)" if bank_search_term else ""
    filter_notice_hg = f" ('{bank_search_term}' filter ke sath)" if bank_search_term else ""

    if lang_code == "en-IN":
        if target_mode == "cash":
            slot_missing_reply = (
                f"💵 **{effective_company} — Cash in Hand Position:**\n\n"
                f"• **Total Cash Balance:** **{_fmt_dr_cr(tot_cash, is_bank=False, lang='en')}**\n"
                f"• **Cash Ledgers Count:** **{len(cash_items)}**\n\n"
                "The interactive Cash Account card is loaded below!"
            )
        elif target_mode == "bank":
            slot_missing_reply = (
                f"🏦 **{effective_company} — Bank Accounts Position{filter_notice_en}:**\n\n"
                f"• **Total Bank Balance:** **{_fmt_dr_cr(tot_bank, is_bank=True, lang='en')}**\n"
                f"• **Active Bank Accounts:** **{len(bank_items)}**\n\n"
            )
            if bank_lines_en:
                slot_missing_reply += f"**Bank Breakdown:**\n{bank_lines_en}\n"
            slot_missing_reply += "The interactive Bank Accounts card is loaded below!"
        else:
            slot_missing_reply = (
                f"💼 **{effective_company} — Cash & Bank Summary:**\n\n"
                f"• **💵 Cash-in-Hand:** **{_fmt_dr_cr(tot_cash, is_bank=False, lang='en')}**\n"
                f"• **🏦 Bank Accounts Total:** **{_fmt_dr_cr(tot_bank, is_bank=True, lang='en')}**\n"
                f"• **💰 Net Liquid Funds:** **{_fmt_dr_cr(tot_liquid, is_bank=False, lang='en')}**\n\n"
            )
            if bank_lines_en:
                slot_missing_reply += f"**Bank Breakdown:**\n{bank_lines_en}\n"
            slot_missing_reply += "The interactive Cash & Bank Ledger Card is loaded below with instant WhatsApp sharing!"

    elif lang_code == "hi-IN":
        if target_mode == "cash":
            slot_missing_reply = (
                f"💵 **{effective_company} — रोकड़ (Cash-in-Hand) स्थिति:**\n\n"
                f"• **कुल कैश बैलेंस:** **{_fmt_dr_cr(tot_cash, is_bank=False, lang='hi')}**\n"
                f"• **कैश खाते:** **{len(cash_items)}**\n\n"
                "नीचे लाइव कैश अकाउंट कार्ड लोड कर दिया गया है!"
            )
        elif target_mode == "bank":
            slot_missing_reply = (
                f"🏦 **{effective_company} — बैंक खाते की स्थिति{filter_notice_hi}:**\n\n"
                f"• **कुल बैंक बैलेंस:** **{_fmt_dr_cr(tot_bank, is_bank=True, lang='hi')}**\n"
                f"• **बैंक खाते संख्या:** **{len(bank_items)}**\n\n"
            )
            if bank_lines_hi:
                slot_missing_reply += f"**बैंक विवरण:**\n{bank_lines_hi}\n"
            slot_missing_reply += "नीचे लाइव बैंक अकाउंट्स कार्ड लोड कर दिया गया है!"
        else:
            slot_missing_reply = (
                f"💼 **{effective_company} — कुल कैश और बैंक विवरण:**\n\n"
                f"• **💵 कैश-इन-हैंड (रोकड़):** **{_fmt_dr_cr(tot_cash, is_bank=False, lang='hi')}**\n"
                f"• **🏦 बैंक खातों का कुल योग:** **{_fmt_dr_cr(tot_bank, is_bank=True, lang='hi')}**\n"
                f"• **💰 कुल लिक्विड फंड्स (उपलब्ध राशि):** **{_fmt_dr_cr(tot_liquid, is_bank=False, lang='hi')}**\n\n"
            )
            if bank_lines_hi:
                slot_missing_reply += f"**बैंक विवरण:**\n{bank_lines_hi}\n"
            slot_missing_reply += "नीचे लाइव कार्ड लोड कर दिया गया है। आप इसे सीधे व्हाट्सएप पर भी शेयर कर सकते हैं!"

    else:  # Hinglish / Default
        if target_mode == "cash":
            slot_missing_reply = (
                f"💵 **{effective_company}** ka **Cash-in-Hand (रोकड़) Balance**:\n\n"
                f"• **Kul Cash Balance:** **{_fmt_dr_cr(tot_cash, is_bank=False, lang='en')}**\n"
                f"• **Cash Accounts:** **{len(cash_items)}**\n\n"
                "Aapke liye interactive Cash Card niche ready hai!"
            )
        elif target_mode == "bank":
            slot_missing_reply = (
                f"🏦 **{effective_company}** ke **Bank Accounts ka Balance{filter_notice_hg}**:\n\n"
                f"• **Kul Bank Balance:** **{_fmt_dr_cr(tot_bank, is_bank=True, lang='en')}**\n"
                f"• **Total Bank Accounts:** **{len(bank_items)}**\n\n"
            )
            if bank_lines_hinglish:
                slot_missing_reply += f"**Bank-wise Breakdown:**\n{bank_lines_hinglish}\n"
            slot_missing_reply += "Aapke liye Bank Accounts card niche live ho chuka hai!"
        else:
            slot_missing_reply = (
                f"💼 **{effective_company}** ka **Cash & Bank Balance** live update:\n\n"
                f"• **💵 Cash-in-Hand:** **{_fmt_dr_cr(tot_cash, is_bank=False, lang='en')}**\n"
                f"• **🏦 Bank Balance:** **{_fmt_dr_cr(tot_bank, is_bank=True, lang='en')}**\n"
                f"• **💰 Kul Liquid Funds:** **{_fmt_dr_cr(tot_liquid, is_bank=False, lang='en')}**\n\n"
            )
            if bank_lines_hinglish:
                slot_missing_reply += f"**Bank Accounts:**\n{bank_lines_hinglish}\n"
            slot_missing_reply += "Niche interactive Cash & Bank card taiyaar hai, jise aap direct WhatsApp par share kar sakte hain!"

    return True, executed_tools, tool_results_text, slot_missing_reply
