import time
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from app.models.conversation import Conversation, ConversationMessage, ConversationSummary
from app.models.tenant import Tenant
from app.models.user import User
from app.models.usage import AIUsage
from app.modules.chat.ai_gateway import ai_gateway
from app.middleware.tenant_context import TenantContext, get_or_resolve_default_tenant_and_user
from app.core.exceptions import NotFoundException
from app.core.pii_scrubber import pii_scrubber
from app.core.semantic_cache import semantic_cache


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _update_rolling_summary_if_needed(self, conversation_id: str, total_count: int):
        """Maintains rolling conversation summary to protect against token blowup and cost attacks."""
        if total_count <= 6:
            return

        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at)
            .limit(total_count - 4)
        )
        res = await self.db.execute(stmt)
        older_msgs = res.scalars().all()
        if not older_msgs:
            return

        summary_points = []
        for m in older_msgs:
            snippet = m.content[:80].replace("\n", " ")
            summary_points.append(f"{m.role.capitalize()}: {snippet}")
        new_summary = "Earlier conversation context: " + "; ".join(summary_points[-5:])

        sum_stmt = select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
        existing_sum = (await self.db.execute(sum_stmt)).scalar_one_or_none()
        if existing_sum:
            existing_sum.summary_text = new_summary
            existing_sum.last_message_id = older_msgs[-1].id
        else:
            created_sum = ConversationSummary(
                conversation_id=conversation_id,
                summary_text=new_summary,
                last_message_id=older_msgs[-1].id,
            )
            self.db.add(created_sum)

    async def process_chat(
        self,
        ctx: TenantContext,
        message_text: str,
        conversation_id: Optional[str] = None,
        company_name: Optional[str] = None,
        user_meta: Optional[Dict[str, Optional[str]]] = None,
    ) -> Dict[str, Any]:
        # 1. Resolve or create conversation
               
        conv = None
        if conversation_id:
            stmt = select(Conversation).where(
                Conversation.id == conversation_id, Conversation.tenant_id == ctx.tenant_id
            )
            res = await self.db.execute(stmt)
            conv = res.scalar_one_or_none()

        # Agar conversation_id nahi aayi ya purani ID DB me nahi mili, toh gracefully nayi conversation bana lo
        if not conv:
            # Multi-tenant integrity guard: Ensure tenant_id and user_id exist in database
            tenant = await self.db.get(Tenant, ctx.tenant_id)
            if not tenant:
                def_tid, def_uid = await get_or_resolve_default_tenant_and_user(self.db)
                ctx = TenantContext(user_id=def_uid, tenant_id=def_tid, role=ctx.role)
            else:
                user = await self.db.get(User, ctx.user_id)
                if not user:
                    _, def_uid = await get_or_resolve_default_tenant_and_user(self.db)
                    ctx = TenantContext(user_id=def_uid, tenant_id=ctx.tenant_id, role=ctx.role)

            conv = Conversation(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                title=message_text[:40] + ("..." if len(message_text) > 40 else ""),
                status="ACTIVE",
            )
            self.db.add(conv)
            await self.db.flush()

        conv_id = str(conv.id)

        # 2. Persist User Message (Original text for authorized user)
        user_msg = ConversationMessage(
            conversation_id=conv_id,
            role="user",
            content=message_text,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # 3. SEMANTIC CACHE CHECK (Strict Multi-Tenant Isolation)
        # All dynamic business queries (sales, invoices, ledgers, vouchers, balance, tickets, connector)
        # MUST ALWAYS bypass cache to guarantee fresh live data and zero cross-user leakage.
        import re
        effective_company_id = (user_meta or {}).get("company_id")
        is_dynamic_business_or_mutation_query = bool(
            re.search(
                r"\b(sales?|bikri|collection|receipts?|jama|orders?|credit\s*notes?|debit\s*notes?|"
                r"vouchers?|invoices?|bills?|payable|receivable|ledgers?|parties?|"
                r"customers?|vendors?|balance|outstanding|baaki|lena|dena|cash|bank|daybook|profit|"
                r"loss|balance\s*sheet|reports?|stock|inventory|items?|tickets?|complaint|connector|"
                r"sync|tally|status|create|bana|generate|daal|karo|kaat|raise|open|बना)\b|"
                r"(बिक्री|सेल्स|खाता|बकाया|कलेक्शन|रसीद|बिल|वाउचर|लेनदेन|स्टॉक|इन्वेंट्री|शिकायत|टिकट)",
                message_text,
                re.IGNORECASE,
            )
        )
        if not is_dynamic_business_or_mutation_query:
            cached_result = await semantic_cache.get_match(
                message_text,
                tenant_id=ctx.tenant_id,
                company_id=effective_company_id,
            )
            if cached_result:
                assistant_msg = ConversationMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content=cached_result["content"],
                    model="semantic-cache-v1",
                    token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    tool_metadata=cached_result.get("tool_calls"),
                )
                self.db.add(assistant_msg)
                await self.db.commit()
                await self.db.refresh(assistant_msg)

                from app.modules.chat.ai_gateway import detect_language_and_script
                detected_info = detect_language_and_script(message_text)
                return {
                    "conversation_id": conv_id,
                    "message_id": assistant_msg.id,
                    "role": "assistant",
                    "content": assistant_msg.content,
                    "citations": [],
                    "tool_calls": cached_result.get("tool_calls", []),
                    "cached": True,
                    "detected_language": detected_info["name"],
                    "language_code": detected_info["code"],
                    "recommended_voice": detected_info["voice"],
                }

        # 4. PII SCRUBBER (Zero-Knowledge Privacy: Mask GSTIN, PAN, Phone before AI processing)
        scrubbed_prompt, pii_mapping = pii_scrubber.scrub(message_text)

        # 5. Check total message count & update summary
        count_stmt = select(func.count(ConversationMessage.id)).where(ConversationMessage.conversation_id == conv_id)
        msg_count = (await self.db.execute(count_stmt)).scalar() or 1
        await self._update_rolling_summary_if_needed(conv_id, msg_count)

        # 6. Fetch rolling context (recent 8 messages for rich multi-turn context)
        history_stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv_id)
            .order_by(desc(ConversationMessage.created_at))
            .limit(8)
        )
        history_res = await self.db.execute(history_stmt)
        recent_messages = list(reversed(history_res.scalars().all()))
        formatted_messages = []
        for m in recent_messages[:-1]:
            formatted_messages.append({"role": m.role, "content": m.content})
        formatted_messages.append({"role": "user", "content": scrubbed_prompt})

        # 6.5 Dynamic Knowledge Base RAG Search
        from app.modules.knowledge.service import KnowledgeService
        knowledge_svc = KnowledgeService(self.db)
        knowledge_chunks = await knowledge_svc.search_knowledge(
            tenant_id=ctx.tenant_id,
            query=scrubbed_prompt,
            top_k=3,
        )

        # 7. Generate AI response via Gateway with dynamic Knowledge Context & DB Session for Ticket Creation
        ai_result = await ai_gateway.generate_response(
            formatted_messages,
            ctx,
            company_name,
            knowledge_context=knowledge_chunks,
            db=self.db,
            conversation_id=conv_id,
            user_meta=user_meta,
        )

        # Restore any PII tokens in response if applicable
        final_content = pii_scrubber.restore(ai_result["content"], pii_mapping)

        # Store in Semantic Cache for future instant replies ONLY if purely generic non-business query without tool calls
        if not is_dynamic_business_or_mutation_query and not ai_result.get("tool_calls"):
            await semantic_cache.store_match(
                message_text,
                final_content,
                ai_result.get("tool_calls"),
                tenant_id=ctx.tenant_id,
                company_id=effective_company_id,
            )

        # 8. Persist Assistant Message
        assistant_msg = ConversationMessage(
            conversation_id=conv_id,
            role="assistant",
            content=final_content,
            model=ai_result.get("model", "patwatoliai-ctrlbooks-subassistant-v1"),
            token_usage=ai_result.get("usage"),
            tool_metadata=ai_result.get("tool_calls"),
        )
        self.db.add(assistant_msg)

        # 9. Record Usage & Metering
        usage_data = ai_result.get("usage", {})
        total_tokens = usage_data.get("total_tokens", 100)
        ai_usage = AIUsage(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            conversation_id=conv_id,
            provider="patwatoliai",
            model=ai_result.get("model", "patwatoliai-ctrlbooks-subassistant-v1"),
            input_tokens=usage_data.get("prompt_tokens", 40),
            output_tokens=usage_data.get("completion_tokens", 60),
            total_tokens=total_tokens,
            estimated_cost=round(total_tokens * 0.000005, 6),
        )
        self.db.add(ai_usage)

        await self.db.commit()
        await self.db.refresh(assistant_msg)

        return {
            "conversation_id": conv_id,
            "message_id": assistant_msg.id,
            "role": "assistant",
            "content": assistant_msg.content,
            "citations": [],
            "tool_calls": ai_result.get("tool_calls", []),
            "cached": False,
            "detected_language": ai_result.get("detected_language", "English"),
            "language_code": ai_result.get("language_code", "en-IN"),
            "recommended_voice": ai_result.get("recommended_voice", "en-IN-PrabhatNeural"),
        }
