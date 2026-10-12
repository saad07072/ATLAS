from backend.app.conversations.errors import ConversationNotFound
from backend.app.conversations.models import (
    DEFAULT_CONVERSATION_TITLE,
    ConversationMessage,
    ConversationRecord,
    ConversationRole,
)
from backend.app.conversations.repository import ConversationRepository

MAX_CONVERSATION_LIST_LIMIT = 100
MAX_CONVERSATION_LIST_OFFSET = 1_000_000
MAX_MESSAGE_PAGE_SIZE = 200
MAX_MESSAGE_PAGE_OFFSET = 1_000_000
CHAT_CONTEXT_MESSAGE_LIMIT = 12


class ConversationService:
    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    def create(
        self,
        user_id: str,
        title: str = DEFAULT_CONVERSATION_TITLE,
    ) -> ConversationRecord:
        return self.repository.create(user_id, title)

    def list(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ConversationRecord], bool]:
        if (
            not 1 <= limit <= MAX_CONVERSATION_LIST_LIMIT
            or not 0 <= offset <= MAX_CONVERSATION_LIST_OFFSET
        ):
            raise ValueError("Conversation pagination is invalid.")
        return self.repository.list(user_id, limit=limit, offset=offset)

    def get(
        self,
        user_id: str,
        conversation_id: str,
        *,
        message_limit: int = 100,
        message_offset: int = 0,
    ) -> tuple[ConversationRecord, list[ConversationMessage], bool]:
        conversation = self.repository.get(user_id, conversation_id)
        if conversation is None:
            raise ConversationNotFound
        if (
            not 1 <= message_limit <= MAX_MESSAGE_PAGE_SIZE
            or not 0 <= message_offset <= MAX_MESSAGE_PAGE_OFFSET
        ):
            raise ValueError("Message history limit is invalid.")
        messages, has_more = self.repository.list_messages(
            user_id,
            conversation_id,
            limit=message_limit,
            offset=message_offset,
        )
        return conversation, messages, has_more

    def rename(
        self,
        user_id: str,
        conversation_id: str,
        title: str,
    ) -> ConversationRecord:
        conversation = self.repository.rename(user_id, conversation_id, title)
        if conversation is None:
            raise ConversationNotFound
        return conversation

    def delete(self, user_id: str, conversation_id: str) -> bool:
        return self.repository.delete(user_id, conversation_id)

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        *,
        role: ConversationRole,
        content: str,
    ) -> ConversationMessage:
        message = self.repository.append_message(
            user_id,
            conversation_id,
            role=role,
            content=content,
        )
        if message is None:
            raise ConversationNotFound
        return message

    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        *,
        excluding_message_id: str,
        max_characters: int = 16000,
    ) -> list[ConversationMessage]:
        messages = self.repository.get_context(
            user_id,
            conversation_id,
            excluding_message_id=excluding_message_id,
            limit=CHAT_CONTEXT_MESSAGE_LIMIT,
        )
        if messages is None:
            raise ConversationNotFound
        selected: list[ConversationMessage] = []
        remaining = max_characters
        for message in reversed(messages):
            if len(message.content) > remaining:
                break
            selected.append(message)
            remaining -= len(message.content)
        return list(reversed(selected))
