class LLMProviderError(RuntimeError):
    """Base exception for provider-related failures."""


class ProviderConfigurationError(LLMProviderError):
    """Raised when required provider settings are missing or invalid."""


class ProviderAuthenticationError(LLMProviderError):
    """Raised when the provider rejects authentication or authorization."""


class ProviderTimeoutError(LLMProviderError):
    """Raised when a provider request exceeds the configured timeout."""


class ProviderRateLimitError(LLMProviderError):
    """Raised when the provider throttles or rate-limits requests."""


class ProviderAPIError(LLMProviderError):
    """Raised for provider API failures that are not otherwise classified."""


class InvalidStructuredOutputError(LLMProviderError):
    """Raised when a structured response cannot be parsed or validated."""


class RetryExhaustedError(LLMProviderError):
    """Raised after all retry attempts have been exhausted."""
