class ConversationError(RuntimeError):
    """Base class for conversation persistence failures."""


class ConversationNotFound(ConversationError):
    """The conversation does not exist for the authenticated user."""


class ConversationStoreUnavailable(ConversationError):
    """Persistent conversation storage is unavailable."""
