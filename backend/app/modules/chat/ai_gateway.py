"""
CtrlBooks Enterprise Multilingual AI Gateway & Orchestrator.

Orchestrates:
- Zero-Click Automatic Language Identification (Auto-LID) and Indian Numeral Normalization
- Strict Accounting & Tally Prime Domain Scope Guardrails
- Modular Domain Handlers (Tickets, Vouchers, Cash/Bank, Parties, Reports, Sales, Lookup, Company)
- Live Tally Connector Telemetry Execution
- Multi-tier LLM Provider Gateway (PatwatoliAI / Mistral / OpenAI / Local fallback)
- Resilient Multilingual Fallback & Grounded Action Card Synthesis
"""

import asyncio
import datetime
import logging
import re
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings
from app.middleware.tenant_context import TenantContext
from app.modules.connector.tools import execute_tool

# Modular Domain Handlers
from app.modules.chat.handlers import (
    handle_ticket_status_check,
    handle_ticket_creation,
    handle_voucher_creation,
    handle_accounting_reports,
    handle_sales_analytics,
    handle_voucher_lookup,
    handle_cash_bank,
    handle_parties,
    handle_connector_status_and_subscription,
    handle_company_details,
    handle_my_entry_and_gst,
)

# Multilingual Linguistic Parsing, Normalization & Fallback Utilities (Re-exported for backward compatibility)
from app.modules.chat.linguistics import (
    INDIAN_DIGIT_MAP,
    normalize_indian_numerals,
    detect_language_and_script,
    extract_voucher_entities,
    _resolve_caller_identity,
    _discover_sample_party,
    _estimate_token_usage,
    _sanitize_brand_identity,
    _is_ctrlbooks_domain_query,
    _build_clean_fallback_reply,
    _build_domain_refusal_reply,
    _get_statutory_reference,
)

logger = logging.getLogger("connector_ai.ai_gateway")


class AIGateway:
    """Multi-provider Enterprise Multilingual AI Gateway with Auto-LID, modular slot-filling, and live Tally tool execution."""

    def __init__(self):
        self.base_url = settings.AI_GATEWAY_BASE_URL.rstrip("/")
        self.api_key = settings.AI_API_KEY
        self.default_model = settings.AI_DEFAULT_MODEL
        self.fallback_model = settings.AI_FALLBACK_MODEL

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        ctx: TenantContext,
        company_name: Optional[str] = None,
        knowledge_context: Optional[List[Dict[str, Any]]] = None,
        db: Optional[Any] = None,
        conversation_id: Optional[str] = None,
        user_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Orchestrates automatic language detection, modular domain handlers,
        live Tally tool execution, and localized response generation.
        """
        last_user_message = messages[-1]["content"].strip() if messages else ""
        detected = detect_language_and_script(last_user_message)
        lang_code = detected["code"]
        lang_name = detected["name"]
        recommended_voice = detected["voice"]

        normalized_msg = normalize_indian_numerals(last_user_message)
        last_msg_lower = normalized_msg.lower()
        raw_company = (company_name or "CtrlBooks").strip()
        active_company = re.sub(
            r"\bCtrlBooks\s+(?:Pvt\.?\s*Ltd\.?|Demo\s+Ltd\.?)\b",
            "CtrlBooks",
            raw_company,
            flags=re.IGNORECASE,
        )
        today_date = datetime.date.today().isoformat()
        caller = _resolve_caller_identity(user_meta, ctx, active_company)

        # Smart Company Disambiguation: Check if user message explicitly mentions a connected company
        if active_company.lower() in ("ctrlbooks", "default", "your company", "connected company", ""):
            try:
                active_token = caller.get("connector_token") or settings.CONNECTOR_API_TOKEN
                if active_token:
                    comp_res = await connector_client._request("GET", "/companies", token=active_token)
                    if comp_res.get("success") and comp_res.get("data"):
                        c_list = comp_res["data"] if isinstance(comp_res["data"], list) else comp_res["data"].get("companies", [])
                        for c in c_list:
                            cname = str(c.get("tallyCompanyName") or c.get("company_name") or c.get("name") or "").strip()
                            if not cname or len(cname) < 3:
                                continue
                            c_words = [w for w in re.split(r"[\s-_]+", cname.lower()) if len(w) >= 4 and w not in ("company", "firm", "limited", "traders", "agency")]
                            clean_cname = re.sub(r"\b(company|firm|ltd|pvt|enterprise|trader|traders|agency)\b", "", cname.lower()).strip()
                            if (cname.lower() in last_msg_lower) or (clean_cname and len(clean_cname) >= 3 and clean_cname in last_msg_lower) or any(w in last_msg_lower for w in c_words):
                                active_company = cname
                                caller["company_id"] = str(c.get("id") or c.get("_id") or caller.get("company_id") or "")
                                caller["company_name"] = cname
                                break
            except Exception:
                pass

        sample_party = _discover_sample_party(active_company)

        executed_tools: List[Dict[str, Any]] = []
        tool_results_text = ""

        # 0. Strict CtrlBooks Domain Scope Guardrail: Reject out-of-scope questions immediately
        if not _is_ctrlbooks_domain_query(last_user_message, messages, active_company=active_company):
            refusal_reply = _build_domain_refusal_reply(lang_code, caller["name"], active_company)
            return {
                "content": refusal_reply,
                "tool_calls": [],
                "usage": _estimate_token_usage(messages, refusal_reply),
                "model": "patwatoliai-ctrlbooks-subassistant-v1",
                "detected_language": lang_name,
                "language_code": lang_code,
                "recommended_voice": recommended_voice,
            }

        # 1. Dynamic Knowledge Context String
        knowledge_prompt_text = ""
        if knowledge_context:
            knowledge_prompt_text = "\n[Verified CtrlBooks Documentation]:\n" + "\n".join(
                f"• {chunk.get('title', 'Guide')}: {chunk.get('content', '')}" for chunk in knowledge_context
            )

        # 1.5 Check Support Ticket Status / Tracking Intent
        slot_missing_reply: Optional[str] = None
        is_check_ticket, tt_tools, tt_text, tt_reply = await handle_ticket_status_check(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            db=db,
        )
        if is_check_ticket:
            executed_tools.extend(tt_tools)
            tool_results_text += tt_text
            if tt_reply:
                slot_missing_reply = tt_reply

        # 2. Check Support Ticket / Escalation Intent (Multilingual Corporate Intake)
        handled_ticket, tc_tools, tc_text, tc_reply = await handle_ticket_creation(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            db=db,
            conversation_id=conversation_id,
            ctx=ctx,
            lang_code=lang_code,
            lang_name=lang_name,
            messages=messages,
            is_check_ticket_intent=is_check_ticket,
        )
        if handled_ticket:
            executed_tools.extend(tc_tools)
            tool_results_text += tc_text
            if tc_reply:
                slot_missing_reply = tc_reply
        is_ticket_intent = handled_ticket

        # 3. Check Live Connection Status & Subscription Intent (Multilingual)
        handled_status_sub, ss_tools, ss_text, ss_reply = await handle_connector_status_and_subscription(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=False,
        )
        if handled_status_sub:
            executed_tools.extend(ss_tools)
            tool_results_text += ss_text
            if ss_reply:
                slot_missing_reply = ss_reply

        # 4. Dynamic Voucher Intent & Slot Filling (Sales, Receipt, Payment, Purchase, Notes, Contra, Journal)
        handled_voucher, v_tools, v_text, v_reply = await handle_voucher_creation(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            ctx=ctx,
            lang_code=lang_code,
            lang_name=lang_name,
            sample_party=sample_party,
            today_date=today_date,
            is_ticket_intent=is_ticket_intent,
            extract_entities_fn=extract_voucher_entities,
        )
        if handled_voucher:
            executed_tools.extend(v_tools)
            tool_results_text += v_text
            if v_reply:
                slot_missing_reply = v_reply
        is_voucher_intent = handled_voucher

        # 4a. Dynamic Cash & Bank Module Intent (Cash in hand, Bank Accounts, Liquid Funds)
        handled_cash_bank, cb_tools, cb_text, cb_reply = await handle_cash_bank(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
        )
        if handled_cash_bank:
            executed_tools.extend(cb_tools)
            tool_results_text += cb_text
            if cb_reply:
                slot_missing_reply = cb_reply
        is_cash_bank_intent = handled_cash_bank

        # 4b. Dynamic Parties & Customer/Supplier Module Intent (Party Balances, Debtors, Outstandings, Contacts)
        handled_parties, p_tools, p_text, p_reply = await handle_parties(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_cash_bank_intent=is_cash_bank_intent,
        )
        if handled_parties:
            executed_tools.extend(p_tools)
            tool_results_text += p_text
            if p_reply:
                slot_missing_reply = p_reply
        is_parties_intent = handled_parties

        # 4c. Dynamic Official Accounting Reports Intent (Day Book, Trial Balance, P&L, Balance Sheet, Voucher Lines)
        handled_reports, r_tools, r_text, r_reply = await handle_accounting_reports(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_cash_bank_intent=is_cash_bank_intent,
            is_parties_intent=is_parties_intent,
        )
        if handled_reports:
            executed_tools.extend(r_tools)
            tool_results_text += r_text
            if r_reply:
                slot_missing_reply = r_reply
        is_accounting_reports_intent = handled_reports

        # 4d. Dynamic Sales & Financial Analytics / Summary Intent (Sales, Receipts, Orders, Credit Notes)
        handled_sales, s_tools, s_text, s_reply = await handle_sales_analytics(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            sample_party=sample_party,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_accounting_reports_intent=is_accounting_reports_intent,
            is_cash_bank_intent=is_cash_bank_intent,
            is_parties_intent=is_parties_intent,
        )
        if handled_sales:
            executed_tools.extend(s_tools)
            tool_results_text += s_text
            if s_reply:
                slot_missing_reply = s_reply
        is_sales_analytics_intent = handled_sales

        # 4e. Dynamic View/Lookup Voucher Intent (Fetches synced invoices/vouchers from Cloud/Tally)
        handled_vlookup, vl_tools, vl_text, vl_reply = await handle_voucher_lookup(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            today_date=today_date,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_sales_analytics_intent=is_sales_analytics_intent,
            is_cash_bank_intent=is_cash_bank_intent,
            is_parties_intent=is_parties_intent,
        )
        if handled_vlookup:
            executed_tools.extend(vl_tools)
            tool_results_text += vl_text
            if vl_reply:
                slot_missing_reply = vl_reply

        # 4f. Dynamic Tally Company Details & Profile Intent (GET /companies & GET /companies/:id)
        handled_company, comp_tools, comp_text, comp_reply = await handle_company_details(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
            is_accounting_reports_intent=is_accounting_reports_intent,
            is_sales_analytics_intent=is_sales_analytics_intent,
            is_cash_bank_intent=is_cash_bank_intent,
            is_parties_intent=is_parties_intent,
        )
        if handled_company:
            executed_tools.extend(comp_tools)
            tool_results_text += comp_text
            if comp_reply:
                slot_missing_reply = comp_reply

        # 4g. Dynamic My Entry Command Queue & Tally Solutions GSTIN Verification
        handled_entry, entry_tools, entry_text, entry_reply = await handle_my_entry_and_gst(
            last_user_message=last_user_message,
            last_msg_lower=last_msg_lower,
            caller=caller,
            active_company=active_company,
            lang_code=lang_code,
            is_ticket_intent=is_ticket_intent,
            is_voucher_intent=is_voucher_intent,
        )
        if handled_entry:
            executed_tools.extend(entry_tools)
            tool_results_text += entry_text
            if entry_reply:
                slot_missing_reply = entry_reply

        elif any(w in last_msg_lower for w in ["sync", "fail", "error", "problem", "nahi ho raha", "सिंक"]):
            sync_data = await execute_tool("get_my_sync_status", {"company_name": active_company}, ctx)
            error_data = await execute_tool("get_my_sync_errors", {"company_name": active_company}, ctx)
            executed_tools.append({"tool": "get_my_sync_status", "result": sync_data})
            executed_tools.append({"tool": "get_my_sync_errors", "result": error_data})
            tool_results_text += f"\n[Live Sync]: Status={sync_data.get('status')}, Last Sync={sync_data.get('last_sync_time')}, Total={sync_data.get('total_records')}, Synced={sync_data.get('synced_records')}"

        # Friendly display name for conversational addressing
        caller_first = caller.get("name", "").split()[0] if caller.get("name") else ""
        friendly_hi = f"{caller_first} ji" if caller_first else "aap"
        friendly_dev = f"{caller_first} जी" if caller_first else "आप"
        friendly_en = caller_first or "there"

        # 5. If remote LLM API key is configured, call remote model
        # Keep exact structured cards for newly created tickets/vouchers or missing-slot prompts, and let live LLM handle conversational queries naturally
        has_action_card = bool(
            slot_missing_reply
            or any(
                t["tool"] in (
                    "create_support_ticket",
                    "create_sales_invoice_command",
                    "create_receipt_voucher_command",
                    "get_sales_analytics_command",
                    "get_accounting_report_command",
                    "get_cash_bank_command",
                    "get_parties_command",
                    "get_connector_status_command",
                    "get_subscription_status_command",
                    "get_company_details_command",
                    "get_my_tally_connections",
                )
                for t in executed_tools
            )
        )
        if (
            not has_action_card
            and self.api_key
            and not self.api_key.startswith("placeholder")
            and not self.api_key.startswith("sk-mock")
            and "your-api-key" not in self.api_key
        ):
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                if lang_code == "en-IN":
                    lang_instruction = (
                        "STRICT LANGUAGE RULE: The user wrote in PURE ENGLISH. "
                        "You MUST reply 100% in natural, warm, conversational English ONLY. Do NOT use Hindi or Hinglish words."
                    )
                elif lang_code == "hi-IN":
                    lang_instruction = (
                        "STRICT LANGUAGE RULE: The user wrote in HINDI (Devanagari script). "
                        "You MUST reply 100% in natural, warm Hindi (Devanagari script: हिंदी) ONLY. Do NOT reply in English or Roman script."
                    )
                elif lang_code == "hinglish":
                    lang_instruction = (
                        "STRICT LANGUAGE RULE: The user wrote in ROMAN HINGLISH (Hindi written in English/Latin alphabet). "
                        f"You MUST reply 100% in natural, friendly conversational Roman Hinglish (addressing the user as '{friendly_hi}'). "
                        "Do NOT sound like a translated textbook or robotic template. Speak like a smart Indian CA / CtrlBooks colleague."
                    )
                else:
                    lang_instruction = (
                        f"STRICT LANGUAGE RULE: The user wrote in {lang_name} ({lang_code}). "
                        f"You MUST reply 100% in {lang_name} using its native script ONLY."
                    )

                system_prompt = (
                    "You are the CtrlBooks AI Assistant — a smart, friendly Accounting & Tally Prime Sub-Assistant built on PatwatoliAI.\n\n"
                    "TONE & CONVERSATION STYLE (VERY IMPORTANT):\n"
                    "- Speak like a sharp, warm, human Chartered Accountant & CtrlBooks expert sitting right next to the user.\n"
                    "- NEVER use stiff, robotic labels like 'Identity:', 'Capabilities:', 'Core Identity:', or 'Summary:'.\n"
                    "- Write naturally with a warm opening sentence followed by 2-4 clean, actionable points only when helpful.\n"
                    f"- Address the user naturally as '{friendly_hi}' (in Hinglish), '{friendly_dev}' (in Hindi), or '{friendly_en}' (in English). Never call the user 'Authorized User' or 'My Company'.\n\n"
                    "STRICT BRANDING & IDENTITY RULE:\n"
                    "- If asked who you are, who built you, or which AI model you are, naturally explain that you are the **CtrlBooks AI Assistant**, a specialized Accounting & Tally Prime **Sub-Assistant of PatwatoliAI**, built to handle Tally Prime live sync, Sales/Receipt vouchers, GST compliance, and instant Support Tickets.\n"
                    "- NEVER mention Mistral, Ministral, OpenAI, ChatGPT, or any third-party AI provider.\n\n"
                    "STRICT DOMAIN RESTRICTION RULE (CTRLBOOKS ONLY):\n"
                    "- You ONLY help with CtrlBooks, Tally Prime sync, Vouchers (Sales/Receipt/Purchase/Payment), Ledgers, GST Compliance (GSTR-1, GSTR-3B, e-Invoice, HSN/SAC), and CtrlBooks Support Tickets.\n"
                    "- If the user asks ANYTHING outside of CtrlBooks / Tally / Accounting / GST, politely decline and ask them to share their issue regarding CtrlBooks.\n\n"
                    f"{lang_instruction}\n\n"
                    f"Today's date: {today_date} | Active Tally Port: {caller.get('tally_port') or 'Auto-Detect'}\n"
                    f"Live Tally & Connector Telemetry:\n{tool_results_text}\n"
                    f"{knowledge_prompt_text}"
                )
                clean_messages = [
                    {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
                    for m in messages[-8:]
                ]
                async with httpx.AsyncClient(timeout=18.0) as client:
                    for attempt, model_to_use in enumerate([self.default_model, self.fallback_model]):
                        payload = {
                            "model": model_to_use,
                            "messages": [{"role": "system", "content": system_prompt}] + clean_messages,
                            "temperature": 0.3,
                            "max_tokens": 700,
                        }
                        res = await client.post(
                            f"{self.base_url.rstrip('/')}/chat/completions",
                            headers=headers,
                            json=payload,
                        )
                        if res.status_code == 200:
                            data = res.json()
                            if "choices" in data and data["choices"]:
                                content = (
                                    data["choices"][0].get("message", {}).get("content")
                                    or data["choices"][0].get("text", "")
                                )
                            else:
                                content = data.get("response") or data.get("content") or data.get("message", "")
                            if content:
                                clean_content = _sanitize_brand_identity(content.strip())
                                usage = data.get("usage") or _estimate_token_usage(messages, clean_content)
                                return {
                                    "content": clean_content,
                                    "tool_calls": executed_tools,
                                    "usage": usage,
                                    "model": "patwatoliai-ctrlbooks-subassistant-v1",
                                    "detected_language": lang_name,
                                    "language_code": lang_code,
                                    "recommended_voice": recommended_voice,
                                }
                        elif res.status_code == 429 and attempt == 0:
                            await asyncio.sleep(1.2)
                            continue
                        else:
                            logger.warning(
                                f"Remote LLM gateway ({self.base_url}/chat/completions, model={model_to_use}) "
                                f"returned HTTP {res.status_code}: {res.text[:200]}"
                            )
                            break
            except Exception as e:
                logger.error(f"Error calling remote LLM gateway: {e}. Falling back to resilient multilingual engine.")

        # 6. Dynamic Grounded Multilingual Response Synthesis (100% Data-Driven from Tool & RAG Outputs)
        if slot_missing_reply:
            reply = slot_missing_reply
        elif knowledge_context:
            first_chunk = knowledge_context[0].get("content", "") if isinstance(knowledge_context, list) and knowledge_context else str(knowledge_context)
            if lang_code == "en-IN":
                reply = f"Hello **{caller['name']}**, based on verified documentation for **{active_company}**:\n\n{first_chunk}"
            elif lang_code == "hi-IN":
                reply = f"नमस्ते **{caller['name']}**, **{active_company}** के सत्यापित दस्तावेज़ों के आधार पर:\n\n{first_chunk}"
            else:
                reply = f"Namaste **{caller['name']}**, **{active_company}** ke verified documentation ke hisab se:\n\n{first_chunk}"
        else:
            statutory_ref = _get_statutory_reference(
                last_msg_lower=last_msg_lower,
                lang_code=lang_code,
                caller_name=caller.get("name", ""),
                active_company=active_company,
                sample_party=sample_party,
            )
            if statutory_ref:
                reply = statutory_ref
            else:
                reply = _build_clean_fallback_reply(lang_code, caller.get("name", ""), active_company)

        clean_reply = _sanitize_brand_identity(reply)
        dynamic_usage = _estimate_token_usage(messages, clean_reply)
        return {
            "content": clean_reply,
            "tool_calls": executed_tools,
            "usage": dynamic_usage,
            "model": "patwatoliai-ctrlbooks-subassistant-v1",
            "detected_language": lang_name,
            "language_code": lang_code,
            "recommended_voice": recommended_voice,
        }


ai_gateway = AIGateway()

__all__ = [
    "AIGateway",
    "ai_gateway",
    "INDIAN_DIGIT_MAP",
    "normalize_indian_numerals",
    "detect_language_and_script",
    "extract_voucher_entities",
    "_resolve_caller_identity",
    "_discover_sample_party",
    "_estimate_token_usage",
    "_sanitize_brand_identity",
    "_is_ctrlbooks_domain_query",
    "_build_clean_fallback_reply",
    "_build_domain_refusal_reply",
]
