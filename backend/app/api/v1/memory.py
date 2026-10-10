from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from backend.app.core.exceptions import ApplicationError
from backend.app.memory.errors import (
    MemoryConflict,
    MemoryNotFound,
    MemoryStoreUnavailable,
)
from backend.app.memory.models import (
    MemoryCandidate,
    MemoryDeleteResponse,
    MemoryListResponse,
    MemoryRecord,
    MemoryType,
    MemoryUpdate,
)
from backend.app.memory.runtime import get_memory_service
from backend.app.memory.service import MemoryService
from backend.app.security.identity import require_authenticated_user_id

router = APIRouter(prefix="/memory")


@router.get("", response_model=MemoryListResponse)
def list_memories(
    memory_type: MemoryType | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: UUID = Depends(require_authenticated_user_id),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryListResponse:
    try:
        return MemoryListResponse(
            memories=service.list(
                str(user_id),
                memory_type=memory_type,
                limit=limit,
            )
        )
    except MemoryStoreUnavailable as exc:
        raise _store_error() from exc


@router.post("", response_model=MemoryRecord, status_code=status.HTTP_200_OK)
def create_memory(
    candidate: MemoryCandidate,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryRecord:
    try:
        return service.create(str(user_id), candidate)
    except MemoryConflict as exc:
        raise ApplicationError(
            str(exc),
            code="memory_conflict",
            status_code=409,
        ) from exc
    except MemoryStoreUnavailable as exc:
        raise _store_error() from exc


@router.put("/{memory_id}", response_model=MemoryRecord)
def update_memory(
    memory_id: UUID,
    changes: MemoryUpdate,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryRecord:
    try:
        return service.update(str(user_id), str(memory_id), changes)
    except MemoryNotFound as exc:
        raise ApplicationError(
            "Memory was not found.",
            code="memory_not_found",
            status_code=404,
        ) from exc
    except MemoryConflict as exc:
        raise ApplicationError(
            str(exc),
            code="memory_conflict",
            status_code=409,
        ) from exc
    except ValueError as exc:
        raise ApplicationError(
            "At least one valid memory field must be updated.",
            code="invalid_memory_update",
            status_code=422,
        ) from exc
    except MemoryStoreUnavailable as exc:
        raise _store_error() from exc


@router.delete(
    "/{memory_id}",
    response_model=MemoryDeleteResponse,
)
def delete_memory(
    memory_id: UUID,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryDeleteResponse:
    try:
        return MemoryDeleteResponse(
            deleted=service.delete(str(user_id), str(memory_id))
        )
    except MemoryStoreUnavailable as exc:
        raise _store_error() from exc


def _store_error() -> ApplicationError:
    return ApplicationError(
        "Persistent memory is unavailable. Please try again later.",
        code="memory_unavailable",
        status_code=503,
    )
