"""Modular Handler for My Entry Command Queue, Entry Cancellation, and Tally GST Verification."""

import re
from typing import Dict, Any, List, Tuple, Optional
from app.modules.connector.client import connector_client


async def handle_my_entry_and_gst(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    lang_code: str,
    is_ticket_intent: bool = False,
    is_voucher_intent: bool = False,
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """
    Handles:
    1. GSTIN Search & Verification via official Tally Solutions API
    2. My Entry commands: Pending/Sent, Completed, Failed tabs
    3. Specific voucher type entry filters: Quotations, Physical Stock, Delivery Notes, Receipt Notes, etc.
    4. Deletion of queued commands
    """
    if is_ticket_intent or is_voucher_intent:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []

    # --------------------------------------------------------------------------
    # 1. GST Verification Intent
    # --------------------------------------------------------------------------
    gst_match = re.search(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b", last_user_message.upper())
    gst_keywords = ["gst", "gstin", "जीएसटी", "verify", "check", "search", "lookup"]
    has_gst_intent = bool(gst_match) or (any(k in last_msg_lower for k in ["gst verify", "gst check", "verify gst", "check gst", "gstin search", "gst number"]))

    if has_gst_intent:
        target_gst = gst_match.group(1) if gst_match else None
        if not target_gst:
            # Check if any alphanumeric 15 digit token exists
            words = re.findall(r"[A-Z0-9]{15}", last_user_message.upper())
            if words:
                target_gst = words[0]

        if target_gst:
            gst_data = await connector_client.search_tally_gst(gstin=target_gst)
            executed_tools.append({"tool": "verify_gstin_command", "result": gst_data})

            if gst_data.get("is_valid"):
                reply = (
                    f"### 🛡️ Verified GSTIN Details (Tally Solutions Portal)\n\n"
                    f"- **GSTIN:** `{gst_data.get('gstin')}`\n"
                    f"- **Trade Name:** **{gst_data.get('trade_name') or 'N/A'}**\n"
                    f"- **Legal Name:** {gst_data.get('legal_name') or 'N/A'}\n"
                    f"- **Status:** 🟢 **{gst_data.get('gstin_status') or 'Active'}** ({gst_data.get('validation_status') or 'VALID'})\n"
                    f"- **Registration Type:** {gst_data.get('registration_type') or 'Regular'}\n"
                    f"- **Registration Date:** {gst_data.get('registration_date') or 'N/A'}\n"
                    f"- **State:** {gst_data.get('state') or 'N/A'} (Code: {gst_data.get('state_code')})\n"
                    f"- **PAN:** `{gst_data.get('pan')}`\n"
                    f"- **City & PIN:** {gst_data.get('city') or ''} - {gst_data.get('pincode') or ''}\n"
                    f"- **Address:** {gst_data.get('address') or 'N/A'}\n\n"
                    f"Aap is party ke liye naya customer/supplier ya voucher bana sakte hain."
                )
            else:
                reply = (
                    f"⚠️ **GSTIN Verification Alert:** `{target_gst}`\n\n"
                    f"- **Status:** {gst_data.get('message', 'Invalid GSTIN or not registered on portal')}\n"
                    f"- **State Code:** {gst_data.get('state_code') or 'N/A'}\n"
                    f"- **PAN Extracted:** `{gst_data.get('pan') or 'N/A'}`\n\n"
                    f"Kripya 15-digit GSTIN number dubara verify karein."
                )
            return True, executed_tools, f"[GST Verified]: {target_gst}", reply

    # --------------------------------------------------------------------------
    # 2. Delete Entry / Command Intent
    # --------------------------------------------------------------------------
    delete_keywords = ["delete entry", "delete command", "entry delete", "command delete", "voucher delete", "hata do", "cancel entry"]
    is_delete_intent = any(k in last_msg_lower for k in delete_keywords)
    if is_delete_intent:
        # Extract command ID (could be uuid, mongodb hex id, or voucher no)
        id_match = re.search(r"\b([a-f0-9]{24}|[a-f0-9\-]{36}|cmd_[a-zA-Z0-9_\-]+)\b", last_user_message, re.IGNORECASE)
        target_cmd_id = id_match.group(1) if id_match else None

        if target_cmd_id:
            del_res = await connector_client.delete_my_entry(
                command_id=target_cmd_id,
                company_name=active_company,
                token=caller.get("connector_token"),
            )
            executed_tools.append({"tool": "delete_my_entry_command", "result": del_res})
            reply = (
                f"✅ **Entry Command Deleted:** `{target_cmd_id}`\n\n"
                f"- **Company:** {active_company}\n"
                f"- **Status:** {del_res.get('message', 'Successfully removed from queue')}\n"
            )
            return True, executed_tools, f"[Entry Deleted]: {target_cmd_id}", reply

    # --------------------------------------------------------------------------
    # 3. My Entry / Command Queue Queries
    # --------------------------------------------------------------------------
    entry_triggers = [
        "my entry",
        "my entries",
        "pending voucher",
        "pending entry",
        "pending entries",
        "sent voucher",
        "failed voucher",
        "failed entry",
        "voucher fail",
        "entry fail",
        "completed entry",
        "command queue",
        "quotation",
        "sales order",
        "purchase order",
        "physical stock",
        "delivery note",
        "receipt note",
        "my parties",
        "my stock items",
        "पेंडिंग",
        "फेल",
        "कोटेशन",
    ]
    is_entry_query = any(k in last_msg_lower for k in entry_triggers) or (
        any(s in last_msg_lower for s in ["fail", "failed", "pending", "completed"])
        and any(w in last_msg_lower for w in ["voucher", "entry", "entries", "bill", "invoice", "command"])
    )
    if not is_entry_query:
        return False, [], "", None

    # Detect Status Filter
    st_filter = None
    if any(k in last_msg_lower for k in ["pending", "sent", "पेंडिंग", "baki"]):
        st_filter = "PENDING,SENT"
    elif any(k in last_msg_lower for k in ["failed", "fail", "error", "रद्द"]):
        st_filter = "FAILED"
    elif any(k in last_msg_lower for k in ["completed", "done", "sync ho gaya", "complete"]):
        st_filter = "DONE"

    # Detect Command Type
    c_type = None
    if "my parties" in last_msg_lower or "party entry" in last_msg_lower:
        c_type = "CREATE_PARTY"
    elif "my stock" in last_msg_lower or "stock item entry" in last_msg_lower:
        c_type = "CREATE_STOCK_ITEM"
    else:
        c_type = "CREATE_VOUCHER"

    # Detect Voucher Type
    v_type = None
    if "quotation" in last_msg_lower or "कोटेशन" in last_msg_lower:
        v_type = "Quotation"
    elif "sales order" in last_msg_lower:
        v_type = "Sales Order"
    elif "purchase order" in last_msg_lower:
        v_type = "Purchase Order"
    elif "physical stock" in last_msg_lower:
        v_type = "Physical Stock"
    elif "delivery note" in last_msg_lower:
        v_type = "Delivery Note"
    elif "receipt note" in last_msg_lower:
        v_type = "Receipt Note"
    elif "sales" in last_msg_lower or "invoice" in last_msg_lower:
        v_type = "Sales"
    elif "receipt" in last_msg_lower:
        v_type = "Receipt"
    elif "payment" in last_msg_lower:
        v_type = "Payment"
    elif "purchase" in last_msg_lower:
        v_type = "Purchase"
    elif "journal" in last_msg_lower:
        v_type = "Journal"
    elif "contra" in last_msg_lower:
        v_type = "Contra"
    elif "credit note" in last_msg_lower:
        v_type = "Credit Note"
    elif "debit note" in last_msg_lower:
        v_type = "Debit Note"

    # Detect Search Keyword (e.g. party name)
    q_search = None
    cleaned = re.sub(
        r"\b(meri|mera|my|entry|entries|vouchers|voucher|batao|dikhao|status|pending|failed|completed|done|sent|tab|ka|ki|ke|in|of|karo)\b",
        "",
        last_msg_lower,
    ).strip()
    if cleaned and len(cleaned) >= 3 and cleaned not in ("quotation", "sales", "purchase", "stock"):
        q_search = cleaned

    entries_data = await connector_client.get_my_entries(
        company_name=active_company,
        command_type=c_type,
        voucher_type=v_type,
        status=st_filter,
        q=q_search,
        page=1,
        limit=20,
        token=caller.get("connector_token"),
    )
    executed_tools.append({"tool": "get_my_entries_command", "result": entries_data})

    items = entries_data.get("items") or []
    tot = entries_data.get("total", len(items))
    title_parts = []
    if st_filter:
        title_parts.append(st_filter)
    if v_type:
        title_parts.append(v_type)
    if c_type and c_type != "CREATE_VOUCHER":
        title_parts.append(c_type)
    heading_title = " ".join(title_parts) if title_parts else "All Command Entries"

    if not items:
        reply = (
            f"📋 **My Entry Queue ({heading_title}):**\n\n"
            f"**{active_company}** me currently koi matching entry nahi mili.\n"
            f"- **Status Filter:** {st_filter or 'All'}\n"
            f"- **Type Filter:** {v_type or c_type or 'All'}\n\n"
            f"Aap naya voucher ya invoice bol kar turant create karwa sakte hain!"
        )
        return True, executed_tools, f"[My Entries]: 0 found for {heading_title}", reply

    lines = [f"📋 **My Entry Queue - {heading_title} ({tot} Total):**\n"]
    for idx, e in enumerate(items[:10], start=1):
        st_icon = "🟢" if e["status"] == "DONE" else ("🔴" if e["status"] == "FAILED" else "🟡")
        amt_str = f" • ₹{e['amount']:,.2f}" if e.get("amount") else ""
        lines.append(
            f"{idx}. {st_icon} **{e.get('voucher_type') or e.get('type')}** `#{e.get('voucher_number') or e.get('id')[:8]}`\n"
            f"   - **Party:** {e.get('party') or 'N/A'}{amt_str}\n"
            f"   - **Status:** `{e.get('status')}` • **Date:** {e.get('date') or 'Recent'}\n"
        )

    if tot > 10:
        lines.append(f"\n*(Showing 10 of {tot} entries. Specific party name search ke liye bol sakte hain)*")

    reply = "\n".join(lines)
    return True, executed_tools, f"[My Entries]: {len(items)} entries returned", reply
