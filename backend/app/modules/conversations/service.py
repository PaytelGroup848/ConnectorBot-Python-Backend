from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, desc
from sqlalchemy.orm import selectinload
from app.models.conversation import Conversation, ConversationMessage, ConversationSummary
from app.core.exceptions import NotFoundException, ForbiddenException


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_conversation(self, tenant_id: str, user_id: str, title: str = "New Conversation") -> Conversation:
        conv = Conversation(tenant_id=tenant_id, user_id=user_id, title=title, status="ACTIVE")
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def list_conversations(
        self, tenant_id: str, user_id: str, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Conversation], int]:
        offset = (page - 1) * page_size
        stmt = (
            select(Conversation)
            .where(Conversation.tenant_id == tenant_id, Conversation.user_id == user_id)
            .order_by(desc(Conversation.updated_at))
            .offset(offset)
            .limit(page_size)
        )
        res = await self.db.execute(stmt)
        items = list(res.scalars().all())
        return items, len(items)

    async def get_conversation_with_messages(
        self, tenant_id: str, user_id: str, conversation_id: str
    ) -> Conversation:
        """Enforces tenant isolation and prevents IDOR vulnerabilities."""
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
            .options(selectinload(Conversation.messages), selectinload(Conversation.summary))
        )
        res = await self.db.execute(stmt)
        conv = res.scalar_one_or_none()
        if not conv:
            raise NotFoundException("Conversation not found")
        if conv.user_id != user_id:
            raise ForbiddenException("Access to this conversation is denied")
        return conv

    async def update_conversation(
        self, tenant_id: str, user_id: str, conversation_id: str, title: Optional[str] = None, status: Optional[str] = None
    ) -> Conversation:
        conv = await self.get_conversation_with_messages(tenant_id, user_id, conversation_id)
        if title is not None:
            conv.title = title
        if status is not None:
            conv.status = status
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def delete_conversation(self, tenant_id: str, user_id: str, conversation_id: str) -> bool:
        conv = await self.get_conversation_with_messages(tenant_id, user_id, conversation_id)
        await self.db.delete(conv)
        await self.db.commit()
        return True

    async def archive_conversation(self, tenant_id: str, user_id: str, conversation_id: str) -> Conversation:
        return await self.update_conversation(tenant_id, user_id, conversation_id, status="ARCHIVED")

