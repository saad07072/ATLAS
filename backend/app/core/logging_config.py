from __future__ import annotations

import logging
import re

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Compiled regexes for high-performance log redaction
REDACTION_PATTERNS = [
    # Bearer tokens
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-\.~+/]+=*"), "Bearer [REDACTED]"),
    # JWT tokens
    (re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    # PEM Private Keys
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    # OAuth authorization codes
    (re.compile(r"(?i)(\bcode=|[?&]code=)[^&\s]+"), r"\g<1>[REDACTED]"),
    # Common sensitive key-value pairs (supports query params, config formats, and JSON strings)
    (
        re.compile(
            r"""(?i)(["']?\b(?:password|secret|client_secret|api_key|access_token|refresh_token|private_key|auth_token)\b["']?\s*[:=]\s*["']?)([^\s,;"'}]+)(["']?)"""
        ),
        r"\g<1>[REDACTED]\g<3>",
    ),
]


def redact_sensitive_text(text: str) -> str:
    """Redacts tokens, credentials, and cryptographic keys from text."""
    redacted = text
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class SensitiveDataRedactingFormatter(logging.Formatter):
    """Logging formatter that automatically redacts credentials and tokens."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact_sensitive_text(original)


def configure_logging(level_name: str) -> None:
    level = logging.getLevelNamesMapping().get(level_name.upper())
    if not isinstance(level, int):
        raise ValueError(f"Unsupported log level: {level_name}")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())

    formatter = SensitiveDataRedactingFormatter(LOG_FORMAT)
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
