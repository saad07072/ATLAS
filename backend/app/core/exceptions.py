class ApplicationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "application_error",
        status_code: int = 400,
    ) -> None:
        if not 400 <= status_code < 600:
            raise ValueError("Application errors must use a 4xx or 5xx status code.")

        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
