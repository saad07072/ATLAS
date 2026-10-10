import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryType(StrEnum):
    USER_PREFERENCE = "user_preference"
    DURABLE_FACT = "durable_fact"
    PROJECT_CONTEXT = "project_context"
    TASK_OUTCOME = "task_outcome"


class MemorySource(StrEnum):
    USER = "user"
    EXPLICIT_SELECTION = "explicit_selection"


_SECRET_PATTERNS = (
    re.compile(
        r"\b(?:api[\s_-]*key|access[\s_-]*token|refresh[\s_-]*token|"
        r"client[\s_-]*secret|password|passwd|credential|private[\s_-]*key|"
        r"secret|bearer)\b\s*(?:is\s+|[:=]\s*)\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),
)
_MEMORY_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")


def contains_secret(content: str) -> bool:
    return any(pattern.search(content) for pattern in _SECRET_PATTERNS)


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MemoryType
    memory_key: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("memory_key")
    @classmethod
    def validate_memory_key(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _MEMORY_KEY_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Memory key must use letters, numbers, dots, underscores, or hyphens."
            )
        return normalized

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Memory content must not be blank.")
        if contains_secret(content):
            raise ValueError("Memory content must not contain credentials or secrets.")
        return content


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MemoryType | None = None
    memory_key: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("memory_key")
    @classmethod
    def validate_memory_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _MEMORY_KEY_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Memory key must use letters, numbers, dots, underscores, or hyphens."
            )
        return normalized

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        content = value.strip()
        if not content:
            raise ValueError("Memory content must not be blank.")
        if contains_secret(content):
            raise ValueError("Memory content must not contain credentials or secrets.")
        return content

    def require_change(self) -> "MemoryUpdate":
        if not self.model_fields_set or not any(
            value is not None for value in self.model_dump().values()
        ):
            raise ValueError("At least one memory field must be updated.")
        return self


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: MemoryType
    memory_key: str
    content: str
    source: MemorySource
    created_at: datetime
    updated_at: datetime
    relevance: float | None = None


class MemoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memories: list[MemoryRecord]


class MemoryDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
