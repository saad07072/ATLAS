from fastapi import APIRouter, Depends

from backend.app.agent.agent import ChatAgent, ChatAgentError
from backend.app.agent.models import ChatRequest, ChatResponse
from backend.app.agent.providers.errors import LLMProviderError
from backend.app.agent.providers.factory import get_llm_provider
from backend.app.config.settings import settings
from backend.app.core.exceptions import ApplicationError
from backend.app.tools.demo import create_demo_tool_service

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
        tool_executor=create_demo_tool_service(),
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    agent: ChatAgent = Depends(get_chat_agent),
) -> ChatResponse:
    try:
        return agent.respond(request)
    except ChatAgentError as exc:
        raise ApplicationError(
            "ATLAS could not complete this response. Please try again.",
            code="chat_unavailable",
            status_code=503,
        ) from exc
