class MemoryError(RuntimeError):
    """Base error for safe memory-service failures."""


class MemoryStoreUnavailable(MemoryError):
    """The persistent memory store is not configured or available."""


class MemoryConflict(MemoryError):
    """A memory key conflicts with an existing memory."""


class MemoryNotFound(MemoryError):
    """The requested user's memory does not exist."""
