import re
import datetime
from typing import Dict, Any, List, Tuple


# Enterprise SLA Matrix by Priority
SLA_MATRIX: Dict[str, Dict[str, str]] = {
    "URGENT": {
        "tier": "P1 - Critical",
        "response_sla": "15 Minutes",
        "resolution_sla": "2 Hours",
        "escalation_team": "L3 Principal Connector Engineering",
    },
    "HIGH": {
        "tier": "P2 - High",
        "response_sla": "1 Hour",
        "resolution_sla": "4 Hours",
        "escalation_team": "L2 Senior Technical Support",
    },
    "NORMAL": {
        "tier": "P3 - Standard",
        "response_sla": "4 Hours",
        "resolution_sla": "24 Hours",
        "escalation_team": "L1 Customer Success & Operations",
    },
}

# Enterprise Issue Taxonomy
CATEGORY_TAXONOMY: List[Dict[str, Any]] = [
    {
        "code": "TALLY-SYNC",
        "name": "Tally Prime Connector & Port {port} Sync",
        "department": "L2 Connector Engineering",
        "keywords": ["tally", "port", "sync", "offline", "connect", "agent", "सिंक", "टैली", "कनेक्ट"],
        "headline": "Port {port} Synchronization & Connector Issue",
        "hypothesis": "Tally Prime XML/HTTP listener on Port {port} experienced a sync handshake interruption or ledger lock.",
        "playbook": "Verify Tally Prime Educational/Silver/Gold mode has 'Enable ODBC/HTTP Server' set to Yes on Port {port}.",
    },
    {
        "code": "GST-COMPLIANCE",
        "name": "GST Filing, GSTR-1/3B & e-Invoice",
        "department": "Tax & Compliance Desk",
        "keywords": ["gst", "gstr", "einvoice", "e-invoice", "eway", "hsn", "irn", "tax", "जीएसटी", "रिटर्न"],
        "headline": "GST Compliance & Tax Return Mismatch",
        "hypothesis": "GSTIN validation or HSN/SAC tax rate mapping mismatch between CtrlBooks queue and Tally master.",
        "playbook": "Inspect party GSTIN state code and verify 9% CGST + 9% SGST vs 18% IGST ledger mapping.",
    },
    {
        "code": "VOUCHER-LEDGER",
        "name": "Voucher Queue & Accounting Ledger",
        "department": "Accounting Operations Desk",
        "keywords": ["voucher", "invoice", "bill", "ledger", "party", "amount", "balance", "payment", "receipt", "इनवॉइस", "बिल", "वाउचर", "लेजर"],
        "headline": "Sales/Receipt Voucher & Ledger Posting Issue",
        "hypothesis": "Target Party Ledger or Sales Account master does not exist in active Tally company.",
        "playbook": "Trigger auto-master creation in CtrlBooks 2-Way Command Queue and re-push voucher hash.",
    },
    {
        "code": "TDS-STATUTORY",
        "name": "TDS Deduction & Statutory Compliance",
        "department": "Statutory Advisory Desk",
        "keywords": ["tds", "194c", "194j", "194q", "194i", "deduction", "pan"],
        "headline": "TDS Section Rate & Threshold Configuration",
        "hypothesis": "TDS Nature of Payment ledger not linked to contractor/professional party ledger.",
        "playbook": "Enable TDS Statutory features (F11) in Tally Prime and map Section 194C/194J rate.",
    },
]


def extract_issue_context_from_conversation(
    current_message: str, history: List[Dict[str, str]]
) -> Tuple[bool, str]:
    """
    Determines whether the user's message (or recent conversation history) contains
    a concrete issue description, or if it is a bare 'create a ticket' request requiring slot-filling.
    """
    generic_strip = re.sub(
        r"\b(bhai|bro|please|plz|ek|naya|new|create|raise|generate|make|open|log|register|support|ticket|complaint|issue|urgent|high|priority|bana|bna|kar|karo|do|de|kijiye|chahiye|for|me|mera|meri|मेरा|एक|नया|सपोर्ट|टिकट|शिकायत|बना|दो|करो)\b",
        " ",
        current_message.lower(),
        flags=re.IGNORECASE,
    )
    generic_strip = re.sub(r"[^\w\u0900-\u097F\u0A80-\u0AFF]+", " ", generic_strip).strip()

    # If remaining meaningful words have at least 4 characters, current message has specific context
    if len(generic_strip) >= 4:
        return True, current_message.strip()

    # Otherwise inspect recent user messages in conversation history for context
    for msg in reversed(history[:-1]):
        if msg.get("role") == "user":
            prev_text = (msg.get("content") or "").strip()
            prev_strip = re.sub(
                r"\b(ticket|complaint|support|bana|create|raise|टिकट)\b",
                "",
                prev_text.lower(),
            ).strip()
            if len(prev_strip) >= 8:
                return True, f"{prev_text} (Escalated via command: '{current_message.strip()}')"

    return False, ""


def classify_corporate_ticket(
    issue_text: str,
    company_name: str,
    detected_language: str,
    tally_status: Dict[str, Any],
    queued_vouchers_count: int,
    caller_name: str = "Authorized User",
    caller_email: str = "user@ctrlbooks.com",
    caller_phone: str = "Session Verified",
) -> Dict[str, Any]:
    """
    Builds a complete Enterprise Corporate Ticket specification including:
    - Category Code & Department Routing
    - Normalized Corporate Subject Line
    - Priority & SLA Matrix (Response + Resolution targets)
    - Live Technical Telemetry & Root Cause Diagnostic Snapshot
    - Cross-Database Caller Identity Bridge (from ctrlbooks.com session)
    """
    lower_issue = issue_text.lower()

    # 1. Match Taxonomy Category & Department
    matched_cat = {
        "code": "TECH-SUPPORT",
        "name": "Platform & Technical Operations",
        "department": "L1 Customer Success & Support",
        "headline": "Technical Support & Operations Inquiry",
        "hypothesis": "User requested technical assistance with CtrlBooks AI workspace.",
        "playbook": "Review conversation transcript and contact customer for screen-share verification.",
    }
    for cat in CATEGORY_TAXONOMY:
        if any(kw in lower_issue for kw in cat["keywords"]):
            matched_cat = cat
            break

    # 2. Determine Priority & SLA Tier
    if any(w in lower_issue for w in ["urgent", "critical", "blocker", "down", "crashed", "emergency", "तुरंत", "जरूरी"]):
        priority = "URGENT"
    elif any(w in lower_issue for w in ["high", "error", "fail", "failed", "not working", "nahi ho raha", "mismatch", "offline", "एरर", "बंद"]):
        priority = "HIGH"
    else:
        priority = "NORMAL"

    sla_info = SLA_MATRIX[priority]

    # 3. Extract Live Diagnostic Port & Telemetry Bundle
    is_online = tally_status.get("is_online", True)
    port = tally_status.get("tally_port") or "Auto"
    agent_ver = tally_status.get("agent_version", "1.0.1")

    cat_name = matched_cat["name"].format(port=port)
    cat_headline = matched_cat["headline"].format(port=port)
    cat_hypothesis = matched_cat["hypothesis"].format(port=port)
    cat_playbook = matched_cat["playbook"].format(port=port)

    # Extract a concise user snippet without filler prefixes
    clean_snippet = re.sub(
        r"^(?:bhai|please|plz|ek|naya|new|create|raise|generate|make|open|log|urgent|high\s+priority|support\s+ticket|ticket|complaint|for|ke\s+liye)\s+",
        "",
        issue_text,
        flags=re.IGNORECASE,
    ).strip()
    if len(clean_snippet) > 55:
        clean_snippet = clean_snippet[:52].rstrip() + "..."

    corporate_subject = f"[{matched_cat['code']}] {cat_headline} — {company_name}"

    telemetry = {
        "company": company_name,
        "customer_name": caller_name,
        "customer_email": caller_email,
        "customer_phone": caller_phone,
        "category_code": matched_cat["code"],
        "category_name": cat_name,
        "department": matched_cat["department"],
        "sla_tier": sla_info["tier"],
        "response_sla": sla_info["response_sla"],
        "resolution_sla": sla_info["resolution_sla"],
        "assigned_team": sla_info["escalation_team"],
        "detected_language": detected_language,
        "source": "CtrlBooks.com Embedded AI Widget",
        "diagnostics": {
            "tally_connector": "ONLINE" if is_online else "OFFLINE",
            "tally_port": port,
            "agent_version": agent_ver,
            "pending_queue_items": queued_vouchers_count,
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "root_cause_hypothesis": cat_hypothesis,
            "engineer_playbook": cat_playbook,
            "customer_summary": clean_snippet,
        },
    }

    return {
        "subject": corporate_subject,
        "priority": priority,
        "category_code": matched_cat["code"],
        "category_name": cat_name,
        "department": matched_cat["department"],
        "sla_tier": sla_info["tier"],
        "response_sla": sla_info["response_sla"],
        "resolution_sla": sla_info["resolution_sla"],
        "assigned_team": sla_info["escalation_team"],
        "ai_summary": telemetry,
    }
