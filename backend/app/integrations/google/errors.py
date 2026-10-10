class GoogleIntegrationError(Exception):
    """Safe, normalized Google integration failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


def normalize_google_status(status_code: int) -> GoogleIntegrationError:
    if status_code == 401:
        return GoogleIntegrationError(
            "authentication_failed",
            "Google authentication failed. Please reconnect the account.",
        )
    if status_code == 403:
        return GoogleIntegrationError(
            "permission_denied",
            "Google denied permission for this operation.",
        )
    if status_code == 404:
        return GoogleIntegrationError(
            "resource_not_found",
            "The requested Google resource was not found.",
        )
    if status_code in {400, 422}:
        return GoogleIntegrationError(
            "invalid_request",
            "Google rejected the request as invalid.",
        )
    return GoogleIntegrationError(
        "google_api_failure",
        "The Google service could not complete the request.",
    )
