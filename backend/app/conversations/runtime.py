from backend.app.config.settings import settings
from backend.app.conversations.repository import PostgresConversationRepository
from backend.app.conversations.service import ConversationService


def get_conversation_service() -> ConversationService:
    return ConversationService(PostgresConversationRepository(settings.database_url))
