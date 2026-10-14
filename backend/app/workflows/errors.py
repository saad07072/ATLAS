from backend.app.core.exceptions import ApplicationError


class WorkflowError(ApplicationError):
    """Base error for all workflow operations."""

    def __init__(
        self,
        message: str = "A workflow error occurred.",
        code: str = "workflow_error",
        status_code: int = 400,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code)


class WorkflowValidationError(WorkflowError):
    """Raised when a workflow plan or step fails validation."""

    def __init__(
        self,
        message: str = "The workflow plan is invalid.",
        code: str = "invalid_workflow_plan",
        status_code: int = 422,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code)


class WorkflowNotFoundError(WorkflowError):
    """Raised when the requested workflow does not exist or does not belong to the user."""

    def __init__(
        self,
        message: str = "The requested workflow was not found.",
        code: str = "workflow_not_found",
        status_code: int = 404,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code)


class WorkflowConflictError(WorkflowError):
    """Raised when a concurrent or invalid state transition is attempted."""

    def __init__(
        self,
        message: str = "The workflow cannot be modified in its current state.",
        code: str = "workflow_conflict",
        status_code: int = 409,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code)


class InvalidStateTransitionError(WorkflowConflictError):
    """Raised when an illegal workflow or step state transition is attempted."""

    def __init__(
        self,
        from_state: str,
        to_state: str,
        entity: str = "workflow",
    ) -> None:
        super().__init__(
            f"Cannot transition {entity} from '{from_state}' to '{to_state}'.",
            code="invalid_state_transition",
        )


class CycleDetectedError(WorkflowValidationError):
    """Raised when a dependency cycle is detected in the workflow DAG."""

    def __init__(self, cycle_path: list[str] | None = None) -> None:
        path_str = f": {' -> '.join(cycle_path)}" if cycle_path else ""
        super().__init__(
            f"Dependency cycle detected in workflow plan{path_str}.",
            code="dependency_cycle_detected",
        )


class WorkflowStoreUnavailable(WorkflowError):
    """Raised when persistent workflow storage cannot be reached."""

    def __init__(
        self,
        message: str = "Persistent workflow storage is unavailable.",
    ) -> None:
        super().__init__(
            message,
            code="workflow_store_unavailable",
            status_code=503,
        )

