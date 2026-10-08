class ToolFrameworkError(Exception):
    """Base class for controlled tool framework failures."""

    code = "tool_error"
    safe_message = "The tool request could not be completed."


class DuplicateToolError(ToolFrameworkError):
    code = "duplicate_tool"
    safe_message = "A tool with this name is already registered."


class UnknownToolError(ToolFrameworkError):
    code = "unknown_tool"
    safe_message = "The requested tool is not available."


class InvalidToolArgumentsError(ToolFrameworkError):
    code = "invalid_arguments"
    safe_message = "Tool arguments are invalid."


class ToolPermissionDeniedError(ToolFrameworkError):
    code = "permission_denied"
    safe_message = "The tool request is not authorized."


class InvalidToolResultError(ToolFrameworkError):
    code = "invalid_result"
    safe_message = "The tool returned an invalid result."


class ToolExecutionError(ToolFrameworkError):
    code = "execution_failed"
    safe_message = "The tool could not complete the request."
