class GitHubIntegrationError(Exception):
    """Safe, normalized GitHub integration failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


def normalize_github_status(
    status_code: int,
    *,
    rate_limit_remaining: str | None = None,
) -> GitHubIntegrationError:
    if status_code == 401:
        return GitHubIntegrationError(
            "authentication_failed",
            "GitHub authentication failed. Check the GitHub App configuration.",
        )
    if status_code == 403 and rate_limit_remaining == "0":
        return GitHubIntegrationError(
            "rate_limited",
            "GitHub API rate limit reached. Please try again later.",
        )
    if status_code == 403:
        return GitHubIntegrationError(
            "permission_denied",
            "The GitHub App is not permitted to perform this operation.",
        )
    if status_code == 404:
        return GitHubIntegrationError(
            "not_found",
            "The requested GitHub resource was not found.",
        )
    if status_code == 409:
        return GitHubIntegrationError(
            "conflict",
            "GitHub could not complete the request because of a conflict.",
        )
    if status_code == 422:
        return GitHubIntegrationError(
            "validation_failed",
            "GitHub rejected the request as invalid.",
        )
    if status_code == 429:
        return GitHubIntegrationError(
            "rate_limited",
            "GitHub API rate limit reached. Please try again later.",
        )
    return GitHubIntegrationError(
        "github_api_error",
        "The GitHub service could not complete the request.",
    )
