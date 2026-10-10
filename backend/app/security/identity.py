from uuid import UUID

from fastapi import Depends

from backend.app.core.exceptions import ApplicationError


def get_optional_authenticated_user_id() -> UUID | None:
    """Identity-provider seam; anonymous access is the only current app mode."""
    return None


def require_authenticated_user_id(
    user_id: UUID | None = Depends(get_optional_authenticated_user_id),
) -> UUID:
    if user_id is None:
        raise ApplicationError(
            "Authentication is required to access memory.",
            code="authentication_required",
            status_code=401,
        )
    return user_id
