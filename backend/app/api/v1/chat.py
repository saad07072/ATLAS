from uuid import UUID

from fastapi import APIRouter, Depends

from backend.app.agent.agent import ChatAgent, ChatAgentError
from backend.app.agent.models import ChatHistoryMessage, ChatRequest, ChatResponse
from backend.app.agent.providers.errors import LLMProviderError
from backend.app.agent.providers.factory import get_llm_provider
from backend.app.config.settings import settings
from backend.app.conversations.errors import (
    ConversationNotFound,
    ConversationStoreUnavailable,
)
from backend.app.conversations.runtime import get_conversation_service
from backend.app.conversations.service import ConversationService
from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.github.runtime import get_tool_executor
from backend.app.memory.runtime import get_memory_service
from backend.app.security.identity import get_authenticated_user_id

router = APIRouter()


def get_chat_agent() -> ChatAgent:
    try:
        provider = get_llm_provider()
    except LLMProviderError as exc:
        raise ApplicationError(
            "ATLAS could not complete this response. Please try again.",
            code="chat_unavailable",
            status_code=503,
        ) from exc

    return ChatAgent(
        provider=provider,
        secret=settings.gemini_api_key,
        tool_executor=get_tool_executor(),
        memory_service=get_memory_service(),
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    agent: ChatAgent = Depends(get_chat_agent),
    user_id: UUID = Depends(get_authenticated_user_id),
    conversations: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    user_id_text = str(user_id)
    if agent.secret and agent.secret in request.message:
        raise ApplicationError(
            "Messages must not contain credentials or secrets.",
            code="invalid_chat_message",
            status_code=422,
        )
    try:
        if request.conversation_id is None:
            conversation = conversations.create(user_id_text)
        else:
            conversation, _, _ = conversations.get(
                user_id_text,
                str(request.conversation_id),
                message_limit=1,
            )
        user_message = conversations.append_message(
            user_id_text,
            conversation.id,
            role="user",
            content=request.message,
        )
    except ConversationNotFound as exc:
        raise _conversation_not_found() from exc
    except ConversationStoreUnavailable as exc:
        raise _conversation_store_error() from exc
    except ValueError as exc:
        raise ApplicationError(
            "Messages must not contain credentials or secrets.",
            code="invalid_chat_message",
            status_code=422,
        ) from exc

    try:
        if request.conversation_id is None and request.history:
            history = request.history
        else:
            history = [
                ChatHistoryMessage(role=message.role, content=message.content)
                for message in conversations.get_context(
                    user_id_text,
                    conversation.id,
                    excluding_message_id=user_message.id,
                    max_characters=16000 - len(request.message),
                )
            ]
        response = agent.respond(
            ChatRequest(
                message=request.message,
                conversation_id=conversation.id,
                history=history,
            ),
            memory_user_id=user_id_text,
        )
    except ChatAgentError as exc:
        raise ApplicationError(
            "ATLAS could not complete this response. Please try again.",
            code="chat_unavailable",
            status_code=503,
        ) from exc
    except ConversationNotFound as exc:
        raise _conversation_not_found() from exc
    except ConversationStoreUnavailable as exc:
        raise _conversation_store_error() from exc

    try:
        conversations.append_message(
            user_id_text,
            conversation.id,
            role="assistant",
            content=response.message,
        )
    except ConversationNotFound as exc:
        raise _conversation_not_found() from exc
    except ConversationStoreUnavailable as exc:
        raise _conversation_store_error() from exc
    except ValueError as exc:
        raise ApplicationError(
            "ATLAS could not complete this response. Please try again.",
            code="chat_unavailable",
            status_code=503,
        ) from exc

    return response.model_copy(update={"conversation_id": UUID(conversation.id)})


def _conversation_not_found() -> ApplicationError:
    return ApplicationError(
        "Conversation was not found.",
        code="conversation_not_found",
        status_code=404,
    )


def _conversation_store_error() -> ApplicationError:
    return ApplicationError(
        "Persistent conversations are unavailable. Please try again later.",
        code="conversation_unavailable",
        status_code=503,
    )
