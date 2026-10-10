from backend.app.config.settings import settings
from backend.app.memory.repository import PostgresMemoryRepository
from backend.app.memory.service import MemoryService


def get_memory_service() -> MemoryService:
    return MemoryService(PostgresMemoryRepository(settings.database_url))
