from backend.app.agent.providers.base import LLMProvider
from backend.app.agent.providers.errors import ProviderConfigurationError
from backend.app.agent.providers.gemini import GeminiProvider
from backend.app.agent.providers.local_offline import LocalOfflineProvider
from backend.app.agent.providers.resilient import ResilientLLMProvider
from backend.app.config.settings import settings


def get_llm_provider() -> LLMProvider:
    provider_name = (settings.llm_provider or "gemini").lower()

    if provider_name in {"local", "offline", "local_offline", "ollama"}:
        return LocalOfflineProvider(settings=settings)

    if provider_name == "gemini":
        gemini = GeminiProvider(settings=settings)
        if getattr(settings, "offline_fallback_enabled", False):
            fallback = LocalOfflineProvider(settings=settings)
            return ResilientLLMProvider(primary=gemini, fallback=fallback, fallback_enabled=True)
        return gemini

    raise ProviderConfigurationError(
        f"Unsupported LLM provider '{settings.llm_provider}'. Supported providers: gemini, local, offline, ollama."
    )
