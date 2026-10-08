class PermissionEngineError(Exception):
    """Base exception for permission policy failures."""


class InvalidPermissionContextError(PermissionEngineError):
    """Raised when a permission context is missing or inconsistent."""
