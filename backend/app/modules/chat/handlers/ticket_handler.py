"""Ticket Handler: Support Ticket status checks, tracking, corporate intake & classification."""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.middleware.tenant_context import TenantContext
from app.modules.connector.client import connector_client
from app.modules.connector.commands import command_queue_service


async def handle_ticket_status_check(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    db: Optional[Any],
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles checking support ticket status and tracking intent."""
    ticket_id_match = re.search(r"CB-\d{8}-[A-Za-z0-9]{4}", last_user_message, re.IGNORECASE)
    is_check_ticket_intent = bool(
        ticket_id_match
        or re.search(
            r"\b(status|track|check|kya hua|update|solve hua|progress|state|closed|resolved|स्टेटस|चेक|अपडेट|सॉल्व)\b.*?\b(ticket|tickets|issue|complaint|शिकायत|टिकट)\b|\b(ticket|tickets|issue|complaint|शिकायत|टिकट)\b.*?\b(status|track|check|kya hua|update|solve hua|progress|state|closed|resolved|स्टेटस|चेक|अपडेट|सॉल्व)\b|\b(mera ticket|my ticket|pichla ticket|ticket ka kya hua)\b",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    if not is_check_ticket_intent or db is None:
        return is_check_ticket_intent, [], "", None

    from app.models.ticket import SupportTicket
    from sqlalchemy import select, desc
    from sqlalchemy.orm import selectinload

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    clean_tid = ticket_id_match.group(0).upper() if ticket_id_match else None
    stmt = select(SupportTicket).options(selectinload(SupportTicket.messages)).order_by(desc(SupportTicket.created_at))
    if clean_tid:
        stmt = stmt.where(SupportTicket.id.ilike(f"%{clean_tid}%"))
    else:
        stmt = stmt.limit(5)

    res = await db.execute(stmt)
    matched_tickets = res.scalars().all()

    if matched_tickets:
        matched = matched_tickets[0]
        agent_msgs = [m for m in matched.messages if m.sender_type in ("AGENT", "SUPPORT") and not m.is_internal]
        latest_reply = agent_msgs[-1].message if agent_msgs else None

        ticket_info = {
            "ticket_id": matched.id,
            "subject": matched.subject,
            "status": matched.status,
            "priority": matched.priority,
            "description": matched.description,
            "created_at": matched.created_at.isoformat(),
            "updated_at": matched.updated_at.isoformat() if matched.updated_at else None,
            "resolved_at": matched.resolved_at.isoformat() if matched.resolved_at else None,
            "engineer_reply": latest_reply,
            "department": (matched.ai_summary or {}).get("department", "L2 Connector Engineering"),
            "sla_tier": (matched.ai_summary or {}).get("sla_tier", "P3 - Standard"),
            "resolution_sla": (matched.ai_summary or {}).get("resolution_sla", "Within 4 Hours"),
            "diagnostics": (matched.ai_summary or {}).get("diagnostics", {}),
            "company": (matched.ai_summary or {}).get("company", active_company),
        }
        executed_tools.append({"tool": "check_support_ticket_status", "result": ticket_info})
        tool_results_text = f"\n[Ticket Status Lookup]: ID={matched.id}, Status={matched.status}, Latest Reply='{latest_reply or 'No engineer notes yet'}'"
    else:
        slot_missing_reply = (
            f"Mujhe **{active_company}** ke liye koi matching support ticket nahi mila"
            + (f" (Ticket #{clean_tid})" if clean_tid else "")
            + ".\n\nAgar aapka koi issue pending hai ya naya ticket raise karna hai, toh boliye main abhi naya ticket bana deta hoon!"
        )

    return True, executed_tools, tool_results_text, slot_missing_reply


async def handle_ticket_creation(
    last_user_message: str,
    last_msg_lower: str,
    caller: Dict[str, Any],
    active_company: str,
    db: Optional[Any],
    conversation_id: Optional[str],
    ctx: TenantContext,
    lang_code: str,
    lang_name: str,
    messages: List[Dict[str, str]],
    is_check_ticket_intent: bool,
) -> Tuple[bool, List[Dict[str, Any]], str, Optional[str]]:
    """Handles support ticket/escalation intent with corporate intake and live diagnostics."""
    is_ticket_intent = (not is_check_ticket_intent) and bool(
        re.search(
            r"\b(ticket|support\s+ticket|complaint|escalate|issue\s+raise|raise\s+a?\s*ticket|log\s+a?\s*ticket|bana do ticket|create ticket)\b|(?:टिकट|शिकायत|सपोर्ट\s*टिकट|ટિકિટ)",
            last_msg_lower,
            re.IGNORECASE,
        )
    )

    if not is_ticket_intent or db is None:
        return False, [], "", None

    from app.modules.tickets.service import TicketService
    from app.modules.tickets.classifier import (
        extract_issue_context_from_conversation,
        classify_corporate_ticket,
    )

    executed_tools: List[Dict[str, Any]] = []
    tool_results_text = ""
    slot_missing_reply: Optional[str] = None

    live_tally = await connector_client.get_connection_status(
        company_name=active_company,
        user_email=caller["email"],
        preferred_port=caller["tally_port"],
    )
    active_p = live_tally.get("tally_port") or "Auto-Detect"
    has_context, full_issue_desc = extract_issue_context_from_conversation(last_user_message, messages)

    if not has_context:
        if lang_code == "en-IN":
            slot_missing_reply = (
                f"I am ready to generate an official **CtrlBooks Enterprise Support Ticket** for **{active_company}**!\n\n"
                "Please briefly describe the issue you are facing so I can route it to the right engineering team with live Tally diagnostics:\n"
                f"• **1. Tally Sync & Port {active_p}**: *'Create a ticket for Tally Port {active_p} sync error'*\n"
                "• **2. GST & e-Invoice**: *'Raise a ticket for GSTR-1 tax mismatch'*\n"
                "• **3. Voucher & Ledger Queue**: *'Create a ticket for pending sales voucher not posting'*"
            )
        elif lang_code == "hi-IN":
            slot_missing_reply = (
                f"मैं **{active_company}** के लिए आधिकारिक **CtrlBooks सपोर्ट टिकट** बनाने के लिए तैयार हूँ!\n\n"
                "कृपया अपनी समस्या का संक्षिप्त विवरण बताएं ताकि सही इंजीनियरिंग टीम को लाइव Tally डायग्नोस्टिक्स के साथ असाइन किया जा सके:\n"
                f"• *'टैली पोर्ट {active_p} सिंक एरर के लिए टिकट बना दो'*\n"
                "• *'GST रिटर्न मिसमैच के लिए टिकट दर्ज करो'*"
            )
        else:
            slot_missing_reply = (
                f"Main **{active_company}** ke liye official **CtrlBooks Corporate Support Ticket** generate karne ke liye ready hoon!\n\n"
                "Kripya apna **Issue / Problem** batayein taaki main live Tally diagnostics ke sath sahi engineering team ko assign kar sakun:\n"
                f"• *'Tally Port {active_p} sync error ke liye urgent ticket bana do'*\n"
                "• *'Sales voucher ledger mismatch ka support ticket raise karo'*\n"
                "• *'GST return filing issue ke liye ticket bana do'*"
            )
        return True, executed_tools, tool_results_text, slot_missing_reply

    queued_cmds = command_queue_service.list_queued_commands()
    company_queue_count = len([c for c in queued_cmds if c.get("company") == active_company])

    spec = classify_corporate_ticket(
        issue_text=full_issue_desc,
        company_name=active_company,
        detected_language=lang_name,
        tally_status=live_tally,
        queued_vouchers_count=company_queue_count,
        caller_name=caller["name"],
        caller_email=caller["email"],
        caller_phone=caller["phone"],
    )

    ticket_svc = TicketService(db)
    db_user_id = str(getattr(ctx, "user_id", None) or "1e336198-e0dc-4ede-bf84-20165e022c67")
    db_tenant_id = str(getattr(ctx, "tenant_id", None) or "3733647b-374b-404a-8dc8-382b7de1abd3")
    try:
        created_ticket = await ticket_svc.create_ticket(
            tenant_id=db_tenant_id,
            user_id=db_user_id,
            subject=spec["subject"],
            description=full_issue_desc,
            priority=spec["priority"],
            conversation_id=conversation_id,
            ai_summary=spec["ai_summary"],
        )
    except Exception:
        await db.rollback()
        created_ticket = await ticket_svc.create_ticket(
            tenant_id="3733647b-374b-404a-8dc8-382b7de1abd3",
            user_id="1e336198-e0dc-4ede-bf84-20165e022c67",
            subject=spec["subject"],
            description=full_issue_desc,
            priority=spec["priority"],
            conversation_id=None,
            ai_summary=spec["ai_summary"],
        )

    t_data = {
        "ticket_id": created_ticket.id,
        "subject": created_ticket.subject,
        "description": full_issue_desc,
        "priority": created_ticket.priority,
        "status": created_ticket.status,
        "company": active_company,
        "user_id": f"{caller['name']} ({caller['email']} | {caller['phone']})",
        "customer_name": caller["name"],
        "customer_email": caller["email"],
        "customer_phone": caller["phone"],
        "category_code": spec["category_code"],
        "category_name": spec["category_name"],
        "department": spec["department"],
        "sla_tier": spec["sla_tier"],
        "response_sla": spec["response_sla"],
        "resolution_sla": spec["resolution_sla"],
        "assigned_team": spec["assigned_team"],
        "diagnostics": spec["ai_summary"]["diagnostics"],
        "created_at": created_ticket.created_at.isoformat(),
    }
    executed_tools.append({"tool": "create_support_ticket", "result": t_data})
    tool_results_text = f"\n[Corporate Support Ticket Created]: ID={created_ticket.id}, Dept={spec['department']}, SLA={spec['resolution_sla']}"

    return True, executed_tools, tool_results_text, None
