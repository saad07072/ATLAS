from backend.app.agent.providers.base import LLMProvider
from backend.app.agent.providers.errors import ProviderConfigurationError
from backend.app.agent.providers.gemini import GeminiProvider
from backend.app.config.settings import settings


def get_llm_provider() -> LLMProvider:
    provider_name = (settings.llm_provider or "gemini").lower()

    if provider_name == "gemini":
        return GeminiProvider(settings=settings)

    raise ProviderConfigurationError(
        f"Unsupported LLM provider '{settings.llm_provider}'. Supported providers: gemini."
    )
