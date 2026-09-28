import asyncio
from app.core.database import engine, Base
# Import all models to ensure they are registered with Base.metadata
from app.models.tenant import Tenant
from app.models.user import User
from app.models.conversation import Conversation, ConversationMessage, ConversationSummary
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.models.ticket import SupportTicket, TicketMessage, TicketEvent
from app.models.usage import AIUsage
from app.models.security_event import SecurityEvent


async def init_tables():
    print("Connecting to PostgreSQL to initialize all tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("SUCCESS: All tables created successfully in connector_ai_db!")


if __name__ == "__main__":
    asyncio.run(init_tables())

