"""Reports Handler: Day Book, Trial Balance, Profit & Loss, Balance Sheet, Voucher Lines."""

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple
from app.modules.connector.client import connector_client


async def handle_accounting_reports(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    lang_code: str,
    is_ticket_intent: bool,
    is_voucher_intent: bool,
    is_cash_bank_intent: bool = False,
    is_parties_intent: bool = False,
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles accounting reports intent (Day Book, Trial Balance, P&L, Balance Sheet, Voucher Lines)."""
    if is_ticket_intent or is_voucher_intent or is_cash_bank_intent or is_parties_intent:
        return False, [], "", None

    is_explicit_reports_keyword = bool(
        re.search(
            r"\b(day\s*book|daybook|trial\s*balance|trail\s*balance|profit\s*(?:and|&)\s*loss|pnl|p&l|balance\s*sheet|voucher\s*lines?|line\s*items?)\b|"
            r"(?:डे\s*बुक|डेबुक|ट्रायल\s*बैलेंस|प्रॉफिट\s*एंड\s*लॉस|बैलेंस\s*शीट|वाउचर\s*लाइन्स)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )
    is_general_reports_request = bool(
        re.search(
            r"\b(mere|mera|apna|apne|my|our|all|aaj\s+ka|aaj\s+ke|daily)\s+(?:aaj\s+ka\s+|daily\s+)?reports?\b|"
            r"\b(reports?\s+(?:do|dikhao|batao|dekhna|generate|chahiye|nikalo))\b|"
            r"\b(aaj\s+ka\s+(?:hisab|khatiyan|transactions?|hisab\s*kitab))\b|"
            r"(?:रिपोर्ट्स?\s*(?:दो|दिखाओ|बताओ)|आज\s*का\s*हिसाब)",
            last_msg_lower,
            re.IGNORECASE,
        )
    ) and not bool(re.search(r"\b(sales?|bikri|orders?|credit\s*notes?)\b", last_msg_lower))

    is_accounting_reports_intent = is_explicit_reports_keyword or is_general_reports_request

    if not is_accounting_reports_intent:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    effective_company = active_company
    effective_company_id = caller.get("company_id")

    # Extract target company candidate if mentioned in the prompt
    comp_patterns = [
        r"^(?:in\s+)?(.*?)\s+(?:me|mein|में)\s+",
        r"(?:company\s+|कंपनी\s+)?([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|company\s+ka|company\s+ki)\s+(?:report|reports|day\s*book|trial|balance|pnl)",
    ]
    for pat in comp_patterns:
        m_c = re.search(pat, last_user_message, re.IGNORECASE)
        if m_c:
            c_cand = m_c.group(1).strip()
            c_cand = re.sub(r"^(?:mere|apne|my|the|in|mujhe|is)\s+", "", c_cand, flags=re.IGNORECASE).strip()
            if len(c_cand) >= 3 and c_cand.lower() not in {"report", "reports", "daybook", "day", "book", "tally", "ctrlbooks"}:
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

    # Detect report type & dates
    today_obj = datetime.date.today()
    today_iso = today_obj.isoformat()

    # Date Range parsing
    if any(w in last_msg_lower for w in ["kal", "yesterday", "pichla din"]):
        y_obj = today_obj - datetime.timedelta(days=1)
        from_date = y_obj.isoformat()
        to_date = y_obj.isoformat()
        period_label = f"Kal ({y_obj.strftime('%d %b %Y')})"
    elif any(w in last_msg_lower for w in ["is mahine", "this month", "current month"]):
        first_day = today_obj.replace(day=1).isoformat()
        from_date = first_day
        to_date = today_iso
        period_label = f"Is Mahine ({today_obj.strftime('%B %Y')})"
    elif any(w in last_msg_lower for w in ["pichle hafte", "last week", "7 din", "7 days"]):
        week_ago = (today_obj - datetime.timedelta(days=7)).isoformat()
        from_date = week_ago
        to_date = today_iso
        period_label = "Pichle 7 Din (Last 7 Days)"
    else:
        from_date = today_iso
        to_date = today_iso
        period_label = f"Aaj ({today_obj.strftime('%d %b %Y')})"

    # Extract search query q if provided
    search_q = None
    q_match = re.search(r"([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|को|का|के)\s+(?:day\s*book|trial|pnl|balance|report)", last_user_message, re.IGNORECASE)
    if q_match:
        cand_q = q_match.group(1).strip()
        cand_q = re.sub(r"^(?:bhai|bro|please|plz|ek|naya|new|mera|mere|apna|apne|aaj|today|kal)\s+", "", cand_q, flags=re.IGNORECASE).strip()
        if len(cand_q) >= 2 and cand_q.lower() not in {"is", "company", "report", "reports", "daybook", "tally", "latest", "last", "aaj"}:
            search_q = cand_q

    # 1. Trial Balance
    if any(w in last_msg_lower for w in ["trial balance", "trail balance", "trial-balance", "ट्रायल बैलेंस"]):
        group_filter = None
        if any(w in last_msg_lower for w in ["debtor", "debtors", "sundry debtors", "देनदार"]):
            group_filter = "Sundry Debtors"
        elif any(w in last_msg_lower for w in ["creditor", "creditors", "sundry creditors", "लेनदार"]):
            group_filter = "Sundry Creditors"
        elif any(w in last_msg_lower for w in ["bank", "banks", "bank accounts"]):
            group_filter = "Bank Accounts"
        elif any(w in last_msg_lower for w in ["cash", "nakad"]):
            group_filter = "Cash-in-hand"

        report_data = await connector_client.get_company_trial_balance(
            company_name=effective_company,
            company_id=effective_company_id,
            page=1,
            limit=50,
            q=search_q,
            group=group_filter,
            token=caller.get("connector_token"),
        )
        report_data["period_label"] = period_label

    # 2. Profit & Loss
    elif any(w in last_msg_lower for w in ["profit and loss", "profit & loss", "pnl", "p&l", "munafa nuksan", "profit loss", "प्रॉफिट"]):
        ledger_type = None
        if any(w in last_msg_lower for w in ["expense", "expenses", "kharcha", "kharch"]):
            ledger_type = "expense"
        elif any(w in last_msg_lower for w in ["income", "aamdani", "revenue"]):
            ledger_type = "income"

        report_data = await connector_client.get_company_pnl(
            company_name=effective_company,
            company_id=effective_company_id,
            page=1,
            limit=50,
            q=search_q,
            ledger_type=ledger_type,
            token=caller.get("connector_token"),
        )
        report_data["period_label"] = period_label

    # 3. Balance Sheet
    elif any(w in last_msg_lower for w in ["balance sheet", "balancesheet", "balance-sheet", "बैलेंस शीट"]):
        ledger_type = None
        if any(w in last_msg_lower for w in ["asset", "assets", "sampatti"]):
            ledger_type = "asset"
        elif any(w in last_msg_lower for w in ["liability", "liabilities", "dayitva"]):
            ledger_type = "liability"

        report_data = await connector_client.get_company_balance_sheet(
            company_name=effective_company,
            company_id=effective_company_id,
            page=1,
            limit=50,
            q=search_q,
            ledger_type=ledger_type,
            token=caller.get("connector_token"),
        )
        report_data["period_label"] = period_label

    # 4. Voucher Lines
    elif any(w in last_msg_lower for w in ["voucher lines", "voucher line", "line items", "लाइन्स"]):
        vid_match = re.search(r"(?:voucher\s*id|voucher|id|#)\s*[:=]?\s*([A-Za-z0-9\-_]{3,})", last_user_message, re.IGNORECASE)
        voucher_id = vid_match.group(1).strip() if vid_match else "VCH-001"

        report_data = await connector_client.get_company_voucher_lines(
            voucher_id=voucher_id,
            company_name=effective_company,
            company_id=effective_company_id,
            page=1,
            limit=100,
            token=caller.get("connector_token"),
        )
        report_data["period_label"] = period_label

    # 5. Day Book (Default for "mere aaj ka reports do", "aaj ka report", "day book", etc.)
    else:
        report_data = await connector_client.get_company_day_book(
            company_name=effective_company,
            company_id=effective_company_id,
            from_date=from_date,
            to_date=to_date,
            page=1,
            limit=50,
            q=search_q,
            token=caller.get("connector_token"),
        )
        report_data["period_label"] = period_label

    executed_tools.append({"tool": "get_accounting_report_command", "result": report_data})
    rep_title = report_data.get("report_title", "Day Book Report")
    rep_type = report_data.get("report_type", "day-book")
    tot_cnt = report_data.get("total_count", 0)
    rows = report_data.get("rows", [])
    tool_results_text = f"\n[Accounting Report]: Type={rep_type}, Title='{rep_title}', Company={effective_company}, Count={tot_cnt}"

    # Format natural language corporate response
    if rep_type == "day-book":
        tot_deb = report_data.get("total_debit", 0.0)
        tot_crd = report_data.get("total_credit", 0.0)
        net_val = report_data.get("net_amount", 0.0)
        top_tx_txt = ""
        for rw in rows[:3]:
            v_no = rw.get("voucher_number", "")
            p_led = rw.get("party_ledger", "Party")
            v_tp = rw.get("voucher_type", "VCH")
            amt = rw.get("amount", 0.0)
            dr_cr = "Dr" if rw.get("debit", 0) > 0 else "Cr"
            top_tx_txt += f"  • `{v_tp} #{v_no}` — **{p_led}**: ₹{amt:,.2f} ({dr_cr})\n"

        if tot_cnt > 0 or tot_deb > 0 or tot_crd > 0:
            if lang_code == "en-IN":
                slot_missing_reply = (
                    f"📊 **{effective_company} — {rep_title} ({period_label}):**\n\n"
                    f"• **Total Day Book Entries:** **{tot_cnt}**\n"
                    f"• **Total Debit:** **₹{tot_deb:,.2f}**\n"
                    f"• **Total Credit:** **₹{tot_crd:,.2f}**\n"
                    f"• **Net Flow:** **₹{net_val:,.2f}**\n\n"
                )
                if top_tx_txt:
                    slot_missing_reply += f"**Key Transactions:**\n{top_tx_txt}\n"
                slot_missing_reply += "The interactive Executive Day Book card has been loaded below with instant WhatsApp sharing!"
            elif lang_code == "hi-IN":
                slot_missing_reply = (
                    f"📊 **{effective_company} — {rep_title} ({period_label}):**\n\n"
                    f"• **कुल दिन की प्रविष्टियाँ:** **{tot_cnt}**\n"
                    f"• **कुल डेबिट:** **₹{tot_deb:,.2f}**\n"
                    f"• **कुल क्रेडिट:** **₹{tot_crd:,.2f}**\n"
                    f"• **नेट फ्लो:** **₹{net_val:,.2f}**\n\n"
                )
                if top_tx_txt:
                    slot_missing_reply += f"**प्रमुख लेनदेन:**\n{top_tx_txt}\n"
                slot_missing_reply += "नीचे लाइव डे बुक कार्ड लोड कर दिया गया है। आप इसे सीधे व्हाट्सएप पर भी शेयर कर सकते हैं!"
            else:
                slot_missing_reply = (
                    f"📊 **{effective_company}** ka **{rep_title}** ({period_label}) mil gaya hai:\n\n"
                    f"• **Kul Day Book Entries:** **{tot_cnt}**\n"
                    f"• **Total Debit:** **₹{tot_deb:,.2f}**\n"
                    f"• **Total Credit:** **₹{tot_crd:,.2f}**\n"
                    f"• **Net Flow:** **₹{net_val:,.2f}**\n\n"
                )
                if top_tx_txt:
                    slot_missing_reply += f"**Top Transactions:**\n{top_tx_txt}\n"
                slot_missing_reply += "Aapke liye interactive live Day Book card niche ready hai, jise aap direct WhatsApp par share kar sakte hain!"
        else:
            slot_missing_reply = f"ℹ️ **{effective_company}** me **{period_label}** ke liye koi Day Book entry nahi mili (Total: ₹0.00).\nAgar aap naya voucher banana chahte hain, toh batayein main abhi Tally me post kar deta hoon!"

    elif rep_type == "trial-balance":
        tot_deb = report_data.get("total_debit", 0.0)
        tot_crd = report_data.get("total_credit", 0.0)
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"⚖️ **{effective_company} — {rep_title}:**\n\n"
                f"• **Total Ledgers / Accounts:** **{tot_cnt}**\n"
                f"• **Total Debit Balance:** **₹{tot_deb:,.2f}**\n"
                f"• **Total Credit Balance:** **₹{tot_crd:,.2f}**\n"
                f"• **Trial Balance Status:** `{'BALANCED' if tot_deb == tot_crd else 'DISCREPANCY CHECK'}`\n\n"
                "The interactive Trial Balance ledger breakdown card is loaded below with WhatsApp export!"
            )
        else:
            slot_missing_reply = (
                f"⚖️ **{effective_company}** ka **{rep_title}** ready hai:\n\n"
                f"• **Total Ledgers:** **{tot_cnt}**\n"
                f"• **Total Debit:** **₹{tot_deb:,.2f}**\n"
                f"• **Total Credit:** **₹{tot_crd:,.2f}**\n\n"
                "Aapke liye verified Trial Balance card niche ready hai!"
            )

    elif rep_type == "pnl":
        tot_inc = report_data.get("total_income", 0.0)
        tot_exp = report_data.get("total_expense", 0.0)
        net_p = report_data.get("net_profit", 0.0)
        p_label = "Net Profit" if net_p >= 0 else "Net Loss"
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"📈 **{effective_company} — Profit & Loss Statement:**\n\n"
                f"• **Total Revenue / Income:** **₹{tot_inc:,.2f}**\n"
                f"• **Total Expenses:** **₹{tot_exp:,.2f}**\n"
                f"• **{p_label}:** **₹{abs(net_p):,.2f}** ({'Profitable' if net_p >= 0 else 'Deficit'})\n\n"
                "The interactive P&L breakdown card is loaded below!"
            )
        else:
            slot_missing_reply = (
                f"📈 **{effective_company}** ka **Profit & Loss Report** ready hai:\n\n"
                f"• **Total Income / Sales:** **₹{tot_inc:,.2f}**\n"
                f"• **Total Expenses:** **₹{tot_exp:,.2f}**\n"
                f"• **{p_label}:** **₹{abs(net_p):,.2f}**\n\n"
                "Aapke liye live P&L statement card niche ready hai!"
            )

    elif rep_type == "balance-sheet":
        tot_ast = report_data.get("total_assets", 0.0)
        tot_lia = report_data.get("total_liabilities", 0.0)
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"🏛️ **{effective_company} — Balance Sheet Report:**\n\n"
                f"• **Total Assets:** **₹{tot_ast:,.2f}**\n"
                f"• **Total Liabilities:** **₹{tot_lia:,.2f}**\n\n"
                "The interactive Balance Sheet breakdown card is loaded below!"
            )
        else:
            slot_missing_reply = (
                f"🏛️ **{effective_company}** ka **Balance Sheet Report** ready hai:\n\n"
                f"• **Total Assets:** **₹{tot_ast:,.2f}**\n"
                f"• **Total Liabilities:** **₹{tot_lia:,.2f}**\n\n"
                "Aapke liye live Balance Sheet card niche ready hai!"
            )

    elif rep_type == "voucher-lines":
        tot_amt = report_data.get("total_amount", 0.0)
        v_id = report_data.get("voucher_id", "")
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"📝 **{effective_company} — Voucher Lines (#{v_id}):**\n\n"
                f"• **Line Items Count:** **{tot_cnt}**\n"
                f"• **Total Itemized Amount:** **₹{tot_amt:,.2f}**\n\n"
                "Item details card is loaded below!"
            )
        else:
            slot_missing_reply = (
                f"📝 **{effective_company}** ka **Voucher #{v_id} Lines** ready hai:\n\n"
                f"• **Total Line Items:** **{tot_cnt}**\n"
                f"• **Total Amount:** **₹{tot_amt:,.2f}**\n\n"
                "Aapke liye voucher line items card niche ready hai!"
            )

    return True, executed_tools, tool_results_text, slot_missing_reply
