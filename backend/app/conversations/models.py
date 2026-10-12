from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.memory.models import contains_secret

ConversationRole = Literal["user", "assistant"]
DEFAULT_CONVERSATION_TITLE = "New conversation"


def _validate_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ValueError("Conversation title must not be blank.")
    if contains_secret(title):
        raise ValueError("Conversation title must not contain credentials or secrets.")
    return title


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default=DEFAULT_CONVERSATION_TITLE, min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validate_title(value)


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validate_title(value)


class ConversationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    conversation_id: str
    role: ConversationRole
    content: str = Field(min_length=1, max_length=8000)
    created_at: datetime

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Message content must not be blank.")
        if contains_secret(content):
            raise ValueError("Messages must not contain credentials or secrets.")
        return content


class ConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversations: list[ConversationRecord]
    limit: int
    offset: int
    has_more: bool


class ConversationDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation: ConversationRecord
    messages: list[ConversationMessage]
    limit: int
    offset: int
    has_more: bool


class ConversationDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
