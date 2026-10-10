from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ChatIntent = Literal[
    "conversation",
    "capability_question",
    "task_request",
    "clarification",
    "unsupported",
]
ChatRole = Literal["user", "assistant"]


class ChatHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ChatRole
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, content: str) -> str:
        content = content.strip()
        if not content:
            raise ValueError("Message content must not be blank.")
        return content


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=12)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, message: str) -> str:
        message = message.strip()
        if not message:
            raise ValueError("Message must not be blank.")
        return message

    @model_validator(mode="after")
    def conversation_context_must_be_bounded(self) -> "ChatRequest":
        total_characters = len(self.message) + sum(
            len(message.content) for message in self.history
        )
        if total_characters > 16000:
            raise ValueError("Conversation context is too long.")
        return self


class ChatResponse(BaseModel):
    intent: ChatIntent
    message: str = Field(min_length=1, max_length=8000)
    requires_clarification: bool = False
