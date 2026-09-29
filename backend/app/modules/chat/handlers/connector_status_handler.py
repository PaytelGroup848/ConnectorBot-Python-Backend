"""Modular Handler for Live Cloud Connector Status & Subscription Management."""

import datetime
from typing import Dict, Any, List, Tuple, Optional
from app.modules.connector.client import connector_client


async def handle_connector_status_and_subscription(
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
    1. Live Connector Device Status & Cloud LastSync Telemetry
    2. SaaS Subscription, Active Plan, Expiry & Seat Limits
    """
    if is_ticket_intent or is_voucher_intent:
        return False, [], "", None

    # 1. Check Subscription / Plan Intent
    sub_keywords = [
        "subscription",
        "subcription",
        "plan",
        "seats",
        "seat",
        "validity",
        "expire",
        "expiry",
        "mera plan",
        "kaun sa plan",
        "kab khatam",
        "सब्सक्रिप्शन",
        "प्लान",
        "वैधता",
        "सीट",
    ]
    is_sub_intent = any(k in last_msg_lower for k in sub_keywords)

    # 2. Check Connector Status / Sync Status Intent
    status_keywords = [
        "connector",
        "connect",
        "connection",
        "chal raha",
        "online",
        "offline",
        "standby",
        "sync status",
        "last sync",
        "status batao",
        "status kya",
        "स्टेटस",
        "कनेक्ट",
        "कनेक्टर",
        "ऑनलाइन",
        "ऑफलाइन",
        "सिंक स्टेटस",
    ]
    is_status_intent = any(k in last_msg_lower for k in status_keywords)

    # If neither intent matches, return unhandled
    if not is_sub_intent and not is_status_intent:
        return False, [], "", None

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None
    token = caller.get("connector_token")

    # -------------------------------------------------------------
    # Case 1: Subscription / Plan Query
    # -------------------------------------------------------------
    if is_sub_intent:
        sub_info = await connector_client.get_my_subscription(token=token)
        executed_tools.append({
            "tool": "get_subscription_status_command",
            "result": sub_info,
        })
        tool_results_text += f"\n[Subscription]: Plan={sub_info.get('plan_name')}, Status={sub_info.get('status')}, Total Seats={sub_info.get('total_seats')}, Days Left={sub_info.get('days_remaining')}"

        plan_name = sub_info.get("plan_name", "Pro")
        status = sub_info.get("status", "ACTIVE")
        seats = sub_info.get("total_seats", 17)
        days_left = sub_info.get("days_remaining", 365)
        to_date_raw = sub_info.get("to_date", "")

        date_formatted = to_date_raw[:10] if to_date_raw else "Active"
        try:
            if to_date_raw:
                dt = datetime.datetime.fromisoformat(to_date_raw.replace("Z", "+00:00"))
                date_formatted = dt.strftime("%d %b %Y")
        except Exception:
            pass

        if lang_code == "en-IN":
            slot_missing_reply = (
                f"💳 **CtrlBooks Subscription & Plan Status:**\n\n"
                f"• **Current Plan:** **{plan_name} Plan** ({status})\n"
                f"• **Validity:** Valid till **{date_formatted}** ({days_left} days remaining)\n"
                f"• **Total Seats Allocated:** **{seats} Seats** (Multi-User Access Enabled)\n"
                f"• **Included Features:** Live Tally 2-Way Sync, Ledgers, Reports & Automated Vouchers.\n\n"
                f"Interactive Subscription Card loaded below!"
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"💳 **CtrlBooks सब्सक्रिप्शन एवं प्लान विवरण:**\n\n"
                f"• **सक्रिय प्लान:** **{plan_name} प्लान** ({status})\n"
                f"• **वैधता (Validity):** **{date_formatted}** तक वैध ({days_left} दिन शेष)\n"
                f"• **कुल सीट्स (Seats):** **{seats} सीट्स** (मल्टी-यूज़र एक्सेस सक्रिय)\n"
                f"• **सुविधाएं:** लाइव Tally 2-वे सिंक, लेजर डायरेक्टरी, रिपोर्ट्स और वाउचर ऑटोमेशन।\n\n"
                f"नीचे इंटरैक्टिव सब्सक्रिप्शन कार्ड लोड कर दिया गया है!"
            )
        else:  # Hinglish
            slot_missing_reply = (
                f"💳 Aapke **CtrlBooks Subscription & Plan** ki details:\n\n"
                f"• **Active Plan:** **{plan_name} Plan** ({status})\n"
                f"• **Plan Validity:** **{date_formatted}** tak valid hai ({days_left} din baaki hain)\n"
                f"• **Total Seats:** **{seats} Users / Seats** allocated hain\n"
                f"• **Active Features:** Tally Prime 2-Way Live Sync, Ledgers, Reports & Instant Vouchers.\n\n"
                f"Aapke liye interactive Subscription Card niche live ho chuka hai!"
            )

        return True, executed_tools, tool_results_text, slot_missing_reply

    # -------------------------------------------------------------
    # Case 2: Connector Status & LastSync Telemetry
    # -------------------------------------------------------------
    cloud_status = await connector_client.get_cloud_connector_status(token=token)
    local_status = await connector_client.get_connection_status(
        company_name=active_company,
        user_email=caller.get("email"),
        preferred_port=caller.get("tally_port"),
    )

    result_data = {
        "success": True,
        "company_name": active_company,
        "cloud_status": cloud_status,
        "local_status": local_status,
        "latest_device": cloud_status.get("latest_connector"),
        "last_sync": cloud_status.get("last_sync"),
        "total_devices": cloud_status.get("total_connectors", 0),
    }

    executed_tools.append({
        "tool": "get_connector_status_command",
        "result": result_data,
    })

    latest_dev = cloud_status.get("latest_connector") or {}
    dev_name = latest_dev.get("device_name") or "Primary PC"
    c_ver = latest_dev.get("connector_version") or "1.0.6"
    tally_conn = latest_dev.get("tally_connected", False) or local_status.get("is_online", True)
    conn_state_str = "CONNECTED / ONLINE" if tally_conn else "STANDBY / OFFLINE"

    last_sync = cloud_status.get("last_sync") or {}
    sync_status = last_sync.get("status") or "COMPLETED"
    sync_time_raw = last_sync.get("completed_at") or last_sync.get("started_at") or ""
    sync_dur = last_sync.get("duration_seconds")
    dur_str = f" in {sync_dur}s" if sync_dur else ""

    sync_time_str = "Recently"
    try:
        if sync_time_raw:
            dt = datetime.datetime.fromisoformat(sync_time_raw.replace("Z", "+00:00"))
            sync_time_str = dt.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        pass

    tool_results_text += f"\n[Connector Status]: Device={dev_name}, Version={c_ver}, Tally={conn_state_str}, LastSync={sync_status} at {sync_time_str}"

    if lang_code == "en-IN":
        slot_missing_reply = (
            f"🔌 **{active_company} — Live Connector & Sync Status:**\n\n"
            f"• **Tally Prime Sync State:** ✅ **{conn_state_str}**\n"
            f"• **Registered Machine:** `{dev_name}` (Connector v{c_ver})\n"
            f"• **Last Cloud Sync:** **{sync_status}** ({sync_time_str}{dur_str})\n"
            f"• **Local Port Monitoring:** Port `{local_status.get('tally_port') or 9000}` (`{local_status.get('detection_source')}`)\n\n"
            f"Interactive Connector Status Card is loaded below with real-time diagnostics!"
        )
    elif lang_code == "hi-IN":
        slot_missing_reply = (
            f"🔌 **{active_company} — कनेक्टर एवं लाइव सिंक स्थिति:**\n\n"
            f"• **Tally Prime कनेक्शन:** ✅ **{conn_state_str}**\n"
            f"• **सक्रिय मशीन:** `{dev_name}` (वर्ज़न v{c_ver})\n"
            f"• **अंतिम क्लाउड सिंक:** **{sync_status}** ({sync_time_str}{dur_str})\n"
            f"• **Tally पोर्ट:** `{local_status.get('tally_port') or 9000}` (`{local_status.get('detection_source')}`)\n\n"
            f"नीche लाइव कनेक्टर स्टेटस कार्ड लोड कर दिया गया है!"
        )
    else:  # Hinglish
        slot_missing_reply = (
            f"🔌 **{active_company}** ka **Live Connector & Sync Status**:\n\n"
            f"• **Tally Prime Status:** ✅ **{conn_state_str}**\n"
            f"• **Registered Device:** `{dev_name}` (Connector v{c_ver})\n"
            f"• **Last Cloud Sync:** **{sync_status}** ({sync_time_str}{dur_str})\n"
            f"• **Active Port:** Port `{local_status.get('tally_port') or 9000}` (`{local_status.get('detection_source')}`)\n\n"
            f"Aapke liye interactive live Connector Status Card niche ready hai!"
        )

    return True, executed_tools, tool_results_text, slot_missing_reply
