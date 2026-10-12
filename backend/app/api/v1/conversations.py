from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from backend.app.conversations.errors import (
    ConversationNotFound,
    ConversationStoreUnavailable,
)
from backend.app.conversations.models import (
    ConversationCreate,
    ConversationDeleteResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationRecord,
    ConversationRename,
)
from backend.app.conversations.runtime import get_conversation_service
from backend.app.conversations.service import ConversationService
from backend.app.core.exceptions import ApplicationError
from backend.app.security.identity import require_authenticated_user_id

router = APIRouter(prefix="/conversations")


@router.post("", response_model=ConversationRecord, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: ConversationCreate,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRecord:
    try:
        return service.create(str(user_id), request.title)
    except ConversationStoreUnavailable as exc:
        raise _store_error() from exc


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user_id: UUID = Depends(require_authenticated_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationListResponse:
    try:
        conversations, has_more = service.list(
            str(user_id),
            limit=limit,
            offset=offset,
        )
        return ConversationListResponse(
            conversations=conversations,
            limit=limit,
            offset=offset,
            has_more=has_more,
        )
    except ConversationStoreUnavailable as exc:
        raise _store_error() from exc


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    user_id: UUID = Depends(require_authenticated_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailResponse:
    try:
        conversation, messages, has_more = service.get(
            str(user_id),
            str(conversation_id),
            message_limit=limit,
            message_offset=offset,
        )
        return ConversationDetailResponse(
            conversation=conversation,
            messages=messages,
            limit=limit,
            offset=offset,
            has_more=has_more,
        )
    except ConversationNotFound as exc:
        raise _not_found() from exc
    except ConversationStoreUnavailable as exc:
        raise _store_error() from exc


@router.patch("/{conversation_id}", response_model=ConversationRecord)
def rename_conversation(
    conversation_id: UUID,
    request: ConversationRename,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRecord:
    try:
        return service.rename(
            str(user_id),
            str(conversation_id),
            request.title,
        )
    except ConversationNotFound as exc:
        raise _not_found() from exc
    except ConversationStoreUnavailable as exc:
        raise _store_error() from exc


@router.delete(
    "/{conversation_id}",
    response_model=ConversationDeleteResponse,
)
def delete_conversation(
    conversation_id: UUID,
    user_id: UUID = Depends(require_authenticated_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDeleteResponse:
    try:
        return ConversationDeleteResponse(
            deleted=service.delete(str(user_id), str(conversation_id))
        )
    except ConversationStoreUnavailable as exc:
        raise _store_error() from exc


def _not_found() -> ApplicationError:
    return ApplicationError(
        "Conversation was not found.",
        code="conversation_not_found",
        status_code=404,
    )


def _store_error() -> ApplicationError:
    return ApplicationError(
        "Persistent conversations are unavailable. Please try again later.",
        code="conversation_unavailable",
        status_code=503,
    )
