from backend.app.tools.base import Tool
from backend.app.tools.errors import DuplicateToolError, UnknownToolError
from backend.app.tools.models import ToolMetadata


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise DuplicateToolError
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError from exc

    def list_tools(self) -> list[ToolMetadata]:
        return [tool.metadata() for tool in self._tools.values()]
