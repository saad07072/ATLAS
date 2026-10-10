from backend.app.memory.errors import MemoryNotFound
from backend.app.memory.models import (
    MemoryCandidate,
    MemoryRecord,
    MemoryType,
    MemoryUpdate,
)
from backend.app.memory.repository import MemoryRepository

MAX_LIST_LIMIT = 100
MAX_RETRIEVAL_LIMIT = 10
MAX_QUERY_CHARACTERS = 500


class MemoryService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def list(
        self,
        user_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise ValueError(f"Limit must be between 1 and {MAX_LIST_LIMIT}.")
        return self.repository.list(
            user_id,
            memory_type=memory_type.value if memory_type else None,
            limit=limit,
        )

    def create(
        self,
        user_id: str,
        candidate: MemoryCandidate,
    ) -> MemoryRecord:
        source = (
            "explicit_selection"
            if candidate.type == MemoryType.TASK_OUTCOME
            else "user"
        )
        return self.repository.create(user_id, candidate, source=source)

    def update(
        self,
        user_id: str,
        memory_id: str,
        changes: MemoryUpdate,
    ) -> MemoryRecord:
        changes.require_change()
        record = self.repository.update(user_id, memory_id, changes)
        if record is None:
            raise MemoryNotFound("Memory was not found.")
        return record

    def delete(self, user_id: str, memory_id: str) -> bool:
        return self.repository.delete(user_id, memory_id)

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 5,
    ) -> list[MemoryRecord]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Memory search query must not be blank.")
        if len(normalized_query) > MAX_QUERY_CHARACTERS:
            raise ValueError("Memory search query is too long.")
        if not 1 <= limit <= MAX_RETRIEVAL_LIMIT:
            raise ValueError(
                f"Retrieval limit must be between 1 and {MAX_RETRIEVAL_LIMIT}."
            )
        return self.repository.retrieve(
            user_id,
            normalized_query,
            memory_type=memory_type.value if memory_type else None,
            limit=limit,
        )
