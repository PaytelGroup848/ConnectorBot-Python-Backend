"""Sales & Analytics Handler: Sales Summary, Receipts, Orders, Credit Notes, and Voucher Lookups."""

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple
from app.modules.connector.client import connector_client


async def handle_sales_analytics(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    lang_code: str,
    sample_party: str,
    is_ticket_intent: bool,
    is_voucher_intent: bool,
    is_accounting_reports_intent: bool,
    is_cash_bank_intent: bool = False,
    is_parties_intent: bool = False,
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles dynamic sales and financial analytics/summary intent (Sales, Receipts, Orders, Credit Notes)."""
    has_specific_vnum = bool(
        re.search(r"(?:invoice|voucher|bill|inv)\s*(?:no\.?|num\.?|#)\s*[A-Za-z0-9\-_]+", last_user_message, re.IGNORECASE)
    ) and not bool(re.search(r"\b(total|aaj|today|kitna|kitni|kitne|summary|report)\b", last_msg_lower))

    is_sales_analytics_intent = (
        (not is_ticket_intent)
        and (not is_voucher_intent)
        and (not is_cash_bank_intent)
        and (not is_parties_intent)
        and (not is_accounting_reports_intent)
        and (not has_specific_vnum)
        and bool(
            re.search(
                r"\b(sales?|bikri|collection|receipts?|jama|orders?|sales\s*orders?|credit\s*notes?)\b.*?\b(batao|dikhao|summary|total|report|kitna|kitni|kitne|aaj|today|yesterday|kal|kya\s+hai|analysis|figure|status)\b|"
                r"\b(aaj|today|kal|yesterday|is\s+mahine|this\s+month|pichle\s+hafte|last\s+week|last\s+\d+\s+days?)\b.*?\b(sales?|bikri|collection|receipts?|orders?|sales\s*orders?|credit\s*notes?)\b|"
                r"\b(mere|mera|apna|apne|my|our|total)\s+(?:aaj\s+ka\s+|today(?:'s)?\s+)?(sales?|bikri|collection|receipts?|orders?|credit\s*notes?)\b|"
                r"(?:आज\s*का\s*सेल्स|आज\s*की\s*बिक्री|कुल\s*सेल्स|आज\s*का\s*कलेक्शन|सेल्स\s*रिपोर्ट)",
                last_msg_lower,
                re.IGNORECASE,
            )
        )
    )

    if not is_sales_analytics_intent:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    effective_company = active_company
    effective_company_id = caller.get("company_id")

    # Determine endpoint and module label
    if any(w in last_msg_lower for w in ["credit note", "credit notes", "creditnote", "sales return", "क्रेडिट नोट"]):
        target_module = "credit-notes"
        module_name = "Credit Note"
    elif any(w in last_msg_lower for w in ["receipt", "receipts", "collection", "jama", "payment", "रसीद"]):
        target_module = "receipts"
        module_name = "Receipt"
    elif any(w in last_msg_lower for w in ["sales order", "sales orders", "salesorder", "order", "orders", "ऑर्डर"]):
        target_module = "sales-orders"
        module_name = "Sales Order"
    else:
        target_module = "sales"
        module_name = "Sales"

    # Determine date range & query intent
    today_obj = datetime.date.today()
    today_iso = today_obj.isoformat()

    is_total_requested = bool(
        re.search(
            r"\b(total|overall|all[\s\-]?time|lifetime|till\s+date|full|sab|poora|pura|kul|complete|gross|all)\b",
            last_msg_lower,
            re.IGNORECASE,
        )
    )
    is_today_requested = bool(
        re.search(
            r"\b(aaj|today|current\s+day|aaj\s+ka|aaj\s+ki)\b",
            last_msg_lower,
            re.IGNORECASE,
        )
    )
    is_yesterday_requested = any(w in last_msg_lower for w in ["kal", "yesterday", "pichla din", "bita kal"])
    is_this_month_requested = any(w in last_msg_lower for w in ["is mahine", "this month", "current month", "is month"])
    is_last_month_requested = any(w in last_msg_lower for w in ["pichla mahina", "last month", "pichle mahine"])
    is_week_requested = any(w in last_msg_lower for w in ["pichle hafte", "last week", "7 din", "7 days", "is hafte", "this week"])
    is_year_requested = any(w in last_msg_lower for w in ["is saal", "this year", "financial year", "fy", "current year"])

    if is_total_requested and not is_today_requested and not is_yesterday_requested:
        from_date = None
        to_date = None
        period_label = "Overall (All-Time Lifetime Total)"
    elif is_today_requested:
        from_date = today_iso
        to_date = today_iso
        period_label = f"Aaj ({today_obj.strftime('%d %b %Y')})"
    elif is_yesterday_requested:
        y_obj = today_obj - datetime.timedelta(days=1)
        from_date = y_obj.isoformat()
        to_date = y_obj.isoformat()
        period_label = f"Kal ({y_obj.strftime('%d %b %Y')})"
    elif is_this_month_requested:
        first_day = today_obj.replace(day=1).isoformat()
        from_date = first_day
        to_date = today_iso
        period_label = f"Is Mahine ({today_obj.strftime('%B %Y')})"
    elif is_last_month_requested:
        first_of_this_month = today_obj.replace(day=1)
        last_day_of_last_month = first_of_this_month - datetime.timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)
        from_date = first_day_of_last_month.isoformat()
        to_date = last_day_of_last_month.isoformat()
        period_label = f"Pichla Mahina ({first_day_of_last_month.strftime('%B %Y')})"
    elif is_week_requested:
        week_ago = (today_obj - datetime.timedelta(days=7)).isoformat()
        from_date = week_ago
        to_date = today_iso
        period_label = "Pichle 7 Din (Last 7 Days)"
    elif is_year_requested:
        fy_year = today_obj.year if today_obj.month >= 4 else today_obj.year - 1
        fy_start = datetime.date(fy_year, 4, 1).isoformat()
        from_date = fy_start
        to_date = today_iso
        period_label = f"Financial Year (FY {fy_year}-{str(fy_year+1)[-2:]})"
    else:
        # Default fallback: When user doesn't mention 'today' or any timeframe,
        # default to active current month rather than single-day 'aaj' to provide useful figures
        first_day = today_obj.replace(day=1).isoformat()
        from_date = first_day
        to_date = today_iso
        period_label = f"Is Mahine ({today_obj.strftime('%B %Y')})"

    # Extract search query q if user specified a party name or voucher query
    search_q = None
    q_match = re.search(r"([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|को|का|के)\s+(?:sales|sale|receipt|collection|order|credit)", last_user_message, re.IGNORECASE)
    if q_match:
        cand_q = q_match.group(1).strip()
        cand_q = re.sub(r"^(?:bhai|bro|please|plz|ek|naya|new|mera|mere|apna|apne|aaj|today|kal)\s+", "", cand_q, flags=re.IGNORECASE).strip()
        time_filter_words = {
            "is", "is mahine", "this month", "current month", "last month", "pichla mahina",
            "pichle mahine", "pichle hafte", "last week", "is hafte", "this week", "aaj",
            "today", "kal", "yesterday", "saal", "year", "this year", "is saal", "total",
            "overall", "all", "sab", "pura", "poora", "kul", "company", "sales", "purchase",
            "bill", "invoice", "voucher", "tally", "latest", "last", "pichla", "bikri", "data",
            "mahina", "mahine", "month", "hafte", "hafta", "week"
        }
        if len(cand_q) >= 2 and cand_q.lower() not in time_filter_words:
            search_q = cand_q

    # Company details resolution
    comp_details = await connector_client.resolve_company_details(
        company_name=effective_company,
        company_id=effective_company_id,
        token=caller.get("connector_token"),
    )
    effective_company = comp_details.get("company_name", effective_company)
    effective_company_id = comp_details.get("company_id", effective_company_id)

    # Query the target module
    analytics_data = await connector_client.get_company_sales_module(
        endpoint_suffix=target_module,
        company_name=effective_company,
        company_id=effective_company_id,
        q=search_q,
        from_date=from_date,
        to_date=to_date,
        page=1,
        limit=20,
        token=caller.get("connector_token"),
    )
    analytics_data["period_label"] = period_label

    executed_tools.append({"tool": "get_sales_analytics_command", "result": analytics_data})
    tot_amt = analytics_data.get("total_amount", 0.0)
    tot_cnt = analytics_data.get("total_count", 0)
    items_list = analytics_data.get("items", [])
    tool_results_text = f"\n[Sales Analytics]: Company={effective_company}, Module={module_name}, Period={period_label}, TotalAmount={tot_amt}, TotalCount={tot_cnt}"

    # Also fetch recent month data if total was requested, so user sees both All-Time and Month figures
    recent_period_amt = 0.0
    recent_period_cnt = 0
    if is_total_requested:
        try:
            trailing_date = (today_obj - datetime.timedelta(days=32)).replace(day=1).isoformat()
            month_snap = await connector_client.get_company_sales_module(
                endpoint_suffix=target_module,
                company_name=effective_company,
                company_id=effective_company_id,
                q=search_q,
                from_date=trailing_date,
                to_date=today_iso,
                page=1,
                limit=3,
                token=caller.get("connector_token"),
            )
            recent_period_amt = float(month_snap.get("total_amount") or 0.0)
            recent_period_cnt = int(month_snap.get("total_count") or 0)
        except Exception:
            pass

    # Format natural language corporate response
    if tot_cnt > 0 or tot_amt > 0:
        top_items_txt = ""
        for itm in items_list[:3]:
            top_items_txt += f"  • `{itm.get('voucher_number', 'VCH')}` — **{itm.get('party_ledger', 'Customer')}**: ₹{itm.get('amount', 0):,.2f}\n"

        period_display = f"{from_date} to {to_date}" if from_date and to_date else "All-Time Lifetime Records (Synced from Tally Prime)"

        month_extra_en = f"• **Current Period / Active Month**: **₹{recent_period_amt:,.2f}** ({recent_period_cnt} vouchers)\n" if (is_total_requested and recent_period_amt > 0) else ""
        month_extra_hi = f"• **हालिया सक्रिय माह (Active Month)**: **₹{recent_period_amt:,.2f}** ({recent_period_cnt} वाउचर)\n" if (is_total_requested and recent_period_amt > 0) else ""
        month_extra_hing = f"• **Recent Period / Active Month**: **₹{recent_period_amt:,.2f}** ({recent_period_cnt} vouchers)\n" if (is_total_requested and recent_period_amt > 0) else ""

        if lang_code == "en-IN":
            slot_missing_reply = (
                f"📊 **{effective_company} — {period_label} {module_name} Report:**\n\n"
                f"• **Total {module_name} Value:** **₹{tot_amt:,.2f}**\n"
                f"• **Total Count:** **{tot_cnt}** {module_name.lower()}(s)\n"
                f"{month_extra_en}"
                f"• **Period Range:** {period_display}\n\n"
            )
            if top_items_txt:
                slot_missing_reply += f"**Key Transactions:**\n{top_items_txt}\n"
            slot_missing_reply += "The interactive financial summary card has been loaded below with instant WhatsApp sharing!"
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"📊 **{effective_company} — {period_label} {module_name} रिपोर्ट:**\n\n"
                f"• **कुल राशि (Total Amount):** **₹{tot_amt:,.2f}**\n"
                f"• **कुल वाउचर/बिल संख्या:** **{tot_cnt}**\n"
                f"{month_extra_hi}"
                f"• **तारीख सीमा:** {period_display}\n\n"
            )
            if top_items_txt:
                slot_missing_reply += f"**प्रमुख लेनदेन:**\n{top_items_txt}\n"
            slot_missing_reply += "नीचे लाइव समरी कार्ड लोड कर दिया गया है। आप इसे सीधे व्हाट्सएप पर भी शेयर कर सकते हैं!"
        else:
            slot_missing_reply = (
                f"📊 **{effective_company}** ka **{period_label}** ka **{module_name}** summary mil gaya hai:\n\n"
                f"• **Kul Bikri / Total Amount:** **₹{tot_amt:,.2f}**\n"
                f"• **Total Vouchers / Invoices:** **{tot_cnt}**\n"
                f"{month_extra_hing}"
                f"• **Date Period:** {period_display}\n\n"
            )
            if top_items_txt:
                slot_missing_reply += f"**Top Transactions:**\n{top_items_txt}\n"
            slot_missing_reply += "Aapke liye interactive live summary card niche ready hai, jise aap direct WhatsApp par share kar sakte hain!"
    else:
        # Resilient real context fallback: If specific period (e.g. Aaj) has 0 records,
        # fetch the latest module records so user gets genuine data and insights
        recent_items = []
        overall_total = 0.0
        overall_count = 0
        month_total = 0.0
        month_count = 0
        try:
            recent_data = await connector_client.get_company_sales_module(
                endpoint_suffix=target_module,
                company_name=effective_company,
                company_id=effective_company_id,
                q=search_q,
                from_date=None,
                to_date=None,
                page=1,
                limit=3,
                token=caller.get("connector_token"),
            )
            recent_items = recent_data.get("items", [])
            overall_total = float(recent_data.get("total_amount") or 0.0)
            overall_count = int(recent_data.get("total_count") or len(recent_items))
        except Exception:
            pass

        try:
            trailing_date = (today_obj - datetime.timedelta(days=32)).replace(day=1).isoformat()
            month_data = await connector_client.get_company_sales_module(
                endpoint_suffix=target_module,
                company_name=effective_company,
                company_id=effective_company_id,
                q=search_q,
                from_date=trailing_date,
                to_date=today_iso,
                page=1,
                limit=3,
                token=caller.get("connector_token"),
            )
            month_total = float(month_data.get("total_amount") or 0.0)
            month_count = int(month_data.get("total_count") or 0)
        except Exception:
            pass

        if recent_items:
            latest_v = recent_items[0]
            v_no = latest_v.get("voucher_number", "VCH")
            p_name = latest_v.get("party_ledger", "Customer")
            amt_val = latest_v.get("amount", 0.0)
            d_val = latest_v.get("date", "")

            month_line_en = f"• **Recent / Active Month**: **₹{month_total:,.2f}** ({month_count} entries)\n" if month_count > 0 else ""
            month_line_hi = f"• **हालिया सक्रिय माह (Recent Month)**: **₹{month_total:,.2f}** ({month_count} वाउचर)\n" if month_count > 0 else ""
            month_line_hing = f"• **Recent Active Period**: **₹{month_total:,.2f}** ({month_count} vouchers)\n" if month_count > 0 else ""

            if lang_code == "en-IN":
                slot_missing_reply = (
                    f"ℹ️ In **{effective_company}**, no new {module_name.lower()} entries were recorded for **{period_label}** (Total: ₹0.00).\n\n"
                    f"{month_line_en}"
                    f"• **Overall All-Time {module_name}**: **₹{overall_total:,.2f}** ({overall_count} entries recorded)\n"
                    f"• **Latest Recorded {module_name}**: `{v_no}` — **{p_name}** (₹{amt_val:,.2f} on {d_val})\n\n"
                    f"Would you like me to create a new {module_name.lower()} voucher in Tally Prime?"
                )
            elif lang_code == "hi-IN":
                slot_missing_reply = (
                    f"ℹ️ **{effective_company}** में **{period_label}** के लिए कोई नई {module_name.lower()} एंट्री नहीं मिली (कुल: ₹0.00)।\n\n"
                    f"{month_line_hi}"
                    f"• **Tally में कुल लाइफटाइम {module_name}**: **₹{overall_total:,.2f}** ({overall_count} रिकॉर्ड)\n"
                    f"• **नवीनतम (Latest) वाउचर**: `{v_no}` — **{p_name}** (₹{amt_val:,.2f}, दिनांक {d_val})\n\n"
                    f"क्या आप नया वाउचर पोस्ट करना चाहते हैं?"
                )
            else:
                slot_missing_reply = (
                    f"ℹ️ **{effective_company}** me **{period_label}** ke liye koi nayi {module_name.lower()} entry nahi mili (Total: ₹0.00).\n\n"
                    f"{month_line_hing}"
                    f"• **Tally me Kul Lifetime {module_name}**: **₹{overall_total:,.2f}** ({overall_count} entries recorded)\n"
                    f"• **Latest {module_name} Entry**: `{v_no}` — **{p_name}** (₹{amt_val:,.2f}, {d_val} ko)\n\n"
                    f"Kya aap naya voucher banana chahte hain ya pichla record dekhna chahte hain?"
                )
        else:
            if lang_code == "en-IN":
                slot_missing_reply = (
                    f"ℹ️ In **{effective_company}**, no {module_name.lower()} records were found for **{period_label}** (Total: ₹0.00).\n\n"
                    f"Would you like me to create a new {module_name.lower()} voucher in Tally Prime?"
                )
            elif lang_code == "hi-IN":
                slot_missing_reply = (
                    f"ℹ️ **{effective_company}** में **{period_label}** के लिए कोई {module_name.lower()} रिकॉर्ड नहीं मिला (कुल: ₹0.00)।\n\n"
                    f"क्या आप नया वाउचर बनाना चाहते हैं?"
                )
            else:
                slot_missing_reply = (
                    f"ℹ️ **{effective_company}** me **{period_label}** ke liye koi {module_name.lower()} entry nahi mili (Total: ₹0.00).\n\n"
                    f"Agar aapko naya voucher banana hai, toh batayein main abhi Tally me post kar deta hoon!"
                )

    return True, executed_tools, tool_results_text, slot_missing_reply


async def handle_voucher_lookup(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    lang_code: str,
    today_date: str,
    is_ticket_intent: bool,
    is_voucher_intent: bool,
    is_sales_analytics_intent: bool,
    is_cash_bank_intent: bool = False,
    is_parties_intent: bool = False,
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles dynamic view/lookup voucher intent (Fetches synced invoices/vouchers from Cloud/Tally)."""
    is_view_voucher_intent = (
        (not is_ticket_intent)
        and (not is_voucher_intent)
        and (not is_sales_analytics_intent)
        and (not is_cash_bank_intent)
        and (not is_parties_intent)
        and bool(
            re.search(
                r"\b(dikhao|dikha|dekho|dekhna|show|view|display|fetch|get|list|find|search|nikalo|batao|pichla|last|latest|previous|kya\s+hai)\b.*?\b(invoice|invoices|invois|bill|bills|voucher|vouchers|receipt|receipts|sale|sales|entry|entries|वाउचर|इनवॉइस|बिल|રસીદ|બિલ)\b|"
                r"\b(invoice|invoices|invois|bill|bills|voucher|vouchers|receipt|receipts|sale|sales|entry|entries|वाउचर|इनवॉइस|बिल|રસીદ|બિલ)\b.*?\b(dikhao|dikha|dekho|dekhna|show|view|display|fetch|get|list|find|search|nikalo|batao|pichla|last|latest|previous)\b|"
                r"\b(mera|mere|apna|apne|my|our)\s+(?:sales\s+)?(invoice|invoices|invois|bill|bills|voucher|vouchers|receipt|receipts|entry|entries)\b|"
                r"(?:दिखाओ|देखो|दिखाना|બતાવો|દાખવા)",
                last_msg_lower,
                re.IGNORECASE,
            )
        )
    )

    if not is_view_voucher_intent:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    effective_company = active_company
    effective_company_id = caller.get("company_id")

    # Extract target company candidate if mentioned in the prompt
    comp_view_patterns = [
        r"^(?:in\s+)?(.*?)\s+(?:me|mein|में)\s+",
        r"(?:company\s+|कंपनी\s+)?([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|company\s+ka|company\s+ki)\s+(?:voucher|invoice|bill|receipt)",
    ]
    for pat in comp_view_patterns:
        m_c = re.search(pat, last_user_message, re.IGNORECASE)
        if m_c:
            c_cand = m_c.group(1).strip()
            c_cand = re.sub(r"^(?:mere|apne|my|the|in|mujhe|is)\s+", "", c_cand, flags=re.IGNORECASE).strip()
            if len(c_cand) >= 3 and c_cand.lower() not in {"bill", "invoice", "voucher", "karo", "tally", "ctrlbooks"}:
                comp_details = await connector_client.resolve_company_details(
                    company_name=c_cand,
                    token=caller.get("connector_token"),
                )
                if comp_details.get("company_id"):
                    effective_company = comp_details.get("company_name", c_cand)
                    effective_company_id = comp_details["company_id"]
                    break

    # If effective_company is generic/default, resolve from connected companies
    if effective_company.lower() in ("ctrlbooks", "your company", "active company", "default", ""):
        try:
            comp_details = await connector_client.resolve_company_details(token=caller.get("connector_token"))
            effective_company = comp_details.get("company_name", effective_company)
            effective_company_id = comp_details.get("company_id", effective_company_id)
        except Exception:
            pass

    # Extract voucher number if specified (e.g., "invoice #2", "bill 101", "INV-12")
    v_num = None
    v_num_match = re.search(r"(?:invoice|voucher|bill|inv|no|number|#)\s*(?:no\.?|num\.?|#)?\s*([A-Za-z0-9\-_]+)", last_user_message, re.IGNORECASE)
    if v_num_match:
        cand_num = v_num_match.group(1).strip()
        if cand_num.lower() not in {"dikhao", "dekho", "view", "show", "hai", "batao", "karo", "mera", "mere", "ke", "ka", "ki", "me", "mein", "sales", "bill", "invoice", "voucher"}:
            v_num = cand_num
    if not v_num:
        v_num_match2 = re.search(r"(\d+)\s*(?:number|no|num)?\s*(?:ka\s+)?(?:bill|invoice|voucher)", last_user_message, re.IGNORECASE)
        if v_num_match2:
            v_num = v_num_match2.group(1).strip()

    # Extract party search query (e.g., "SuperFoods ka bill dikhao")
    party_search = None
    party_match = re.search(r"([A-Za-z0-9\s&.\'-]+?)\s+(?:ka|ki|ke|को|का|के)\s+(?:bill|invoice|voucher|इनवॉइस|बिल|वाउचर)", last_user_message, re.IGNORECASE)
    if party_match:
        cand_party = party_match.group(1).strip()
        cand_party = re.sub(r"^(?:bhai|bro|please|plz|ek|naya|new|mera|mere|apna|apne)\s+", "", cand_party, flags=re.IGNORECASE).strip()
        if len(cand_party) >= 2 and cand_party.lower() not in {"is", "company", "sales", "purchase", "bill", "invoice", "voucher", "tally", "latest", "last", "pichla"}:
            if cand_party.lower() not in effective_company.lower() and effective_company.lower() not in cand_party.lower():
                party_search = cand_party

    v_type_filter = "Receipt" if any(w in last_msg_lower for w in ["receipt", "रसीद"]) else "Sales"

    # Query real-time synchronized vouchers from CtrlBooks Cloud API / Tally Prime
    vouchers = await connector_client.get_company_vouchers(
        company_name=effective_company,
        company_id=effective_company_id,
        voucher_type=v_type_filter,
        voucher_number=v_num,
        search=party_search,
        limit=5,
        token=caller.get("connector_token"),
    )

    if vouchers:
        top_v = vouchers[0]
        top_amt = 0.0
        try:
            raw_val = top_v.get("amount")
            if isinstance(raw_val, dict):
                raw_val = raw_val.get("$numberDecimal") or raw_val.get("value") or 0.0
            top_amt = float(str(raw_val).replace(",", "").strip() if raw_val is not None and str(raw_val).strip() != "" else 0.0)
        except Exception:
            top_amt = 0.0

        top_items = top_v.get("items") or []
        if not top_items:
            top_items = [{
                "name": f"{top_v.get('voucher_type', 'Sales')} - {top_v.get('party_ledger')}",
                "itemName": f"{top_v.get('voucher_type', 'Sales')} - {top_v.get('party_ledger')}",
                "quantity": 1,
                "rate": top_amt,
                "amount": top_amt,
            }]

        card_data = {
            "success": True,
            "status": top_v.get("status", "SYNCED"),
            "command_type": "CREATE_VOUCHER",
            "command_hash": top_v.get("id") or "synced_voucher",
            "command_id": top_v.get("id"),
            "voucher_number": top_v.get("voucher_number"),
            "company": effective_company,
            "company_id": effective_company_id,
            "party_name": top_v.get("party_ledger"),
            "payload": {
                "type": "CREATE_VOUCHER",
                "companyName": effective_company,
                "payload": {
                    "voucher_type": top_v.get("voucher_type", "Sales"),
                    "party_ledger": top_v.get("party_ledger"),
                    "date": top_v.get("date"),
                    "amount": top_amt,
                    "taxable_amount": top_amt,
                    "gst_total": 0.0,
                    "narration": top_v.get("narration") or f"Invoice #{top_v.get('voucher_number')}",
                    "items": top_items,
                },
            },
        }

        executed_tools.append({"tool": "create_sales_invoice_command", "result": card_data})
        executed_tools.append({"tool": "get_company_vouchers_command", "result": {"vouchers": vouchers, "count": len(vouchers)}})
        tool_results_text = f"\n[Vouchers Retrieved]: Company={effective_company}, Total={len(vouchers)}, TopVoucher={top_v.get('voucher_number')}, Party={top_v.get('party_ledger')}, Amount={top_amt}"

        v_num_disp = top_v.get("voucher_number", "N/A")
        party_disp = top_v.get("party_ledger", "Customer")
        amt_disp = top_amt
        date_disp = top_v.get("date") or today_date
        v_type_disp = top_v.get("voucher_type", "Sales")
        status_disp = top_v.get("status", "SYNCED")

        if lang_code == "en-IN":
            slot_missing_reply = (
                f"Here is the verified **{v_type_disp} Invoice** for **{party_disp}** from **{effective_company}**:\n\n"
                f"• **Company**: {effective_company}\n"
                f"• **Invoice Number**: `{v_num_disp}`\n"
                f"• **Party Name**: {party_disp}\n"
                f"• **Date**: {date_disp}\n"
                f"• **Total Amount**: ₹{amt_disp:,.2f}\n"
                f"• **Tally Sync Status**: `{status_disp}`\n\n"
                f"The interactive invoice card has been loaded below with full details and instant WhatsApp sharing!"
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"ये रहा **{effective_company}** में **{party_disp}** का **{v_type_disp} इनवॉइस**:\n\n"
                f"• **कंपनी**: {effective_company}\n"
                f"• **इनवॉइस नंबर**: `{v_num_disp}`\n"
                f"• **पार्टी का नाम**: {party_disp}\n"
                f"• **दिनांक**: {date_disp}\n"
                f"• **कुल राशि**: ₹{amt_disp:,.2f}\n"
                f"• **टैली सिंक स्टेटस**: `{status_disp}`\n\n"
                f"नीचे डिजिटल इनवॉइस कार्ड लोड कर दिया गया है। आप इसे सीधे व्हाट्सएप पर भी शेयर कर सकते हैं!"
            )
        else:
            slot_missing_reply = (
                f"Ji bhai! **{effective_company}** ka verified **{v_type_disp} Invoice** mil gaya hai:\n\n"
                f"• **Company**: {effective_company}\n"
                f"• **Invoice Number**: `{v_num_disp}`\n"
                f"• **Party Name**: {party_disp}\n"
                f"• **Date**: {date_disp}\n"
                f"• **Total Amount**: ₹{amt_disp:,.2f}\n"
                f"• **Tally Sync Status**: `{status_disp}`\n\n"
                f"Aapke liye interactive digital invoice card niche ready hai, jise aap direct WhatsApp par share ya print kar sakte hain!"
            )
    else:
        executed_tools.append({"tool": "get_company_vouchers_command", "result": {"vouchers": [], "count": 0}})
        search_detail = f" ('{party_search}' ke liye)" if party_search else ""
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"No vouchers were found in **{effective_company}**{search_detail}.\n\n"
                f"Would you like me to create a new invoice for this party? (e.g. *'Create sales invoice for {party_search or 'SuperFoods'} of ₹5,000'*)"
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"**{effective_company}** में कोई वाउचर नहीं मिला{search_detail}।\n\n"
                f"क्या आप नया इनवॉइस बनाना चाहते हैं? (जैसे: *'{party_search or 'SuperFoods'} के लिए 5,000 का बिल बना दो'*)"
            )
        else:
            slot_missing_reply = (
                f"**{effective_company}** me abhi koi voucher nahi mila{search_detail}.\n\n"
                f"Kya aap naya voucher create karna chahte hain? Example: *'{party_search or 'SuperFoods'} ko 5000 ka bill bana do'*"
            )

    return True, executed_tools, tool_results_text, slot_missing_reply
