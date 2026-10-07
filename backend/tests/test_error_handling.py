import json
import logging
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Query
from starlette.types import Message, Scope

from backend.app.config.settings import settings
from backend.app.config.settings import Settings
from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.exceptions import ApplicationError
from backend.app.core.logging_config import configure_logging
from backend.app.main import app as application


def create_test_app() -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/known-error")
    async def raise_application_error() -> None:
        raise ApplicationError(
            "The requested item was not found.",
            code="item_not_found",
            status_code=404,
        )

    @test_app.get("/unexpected-error")
    async def raise_unexpected_error() -> None:
        raise RuntimeError("internal details must not be returned")

    @test_app.get("/validated")
    async def validate_request(limit: int = Query(gt=0)) -> dict[str, int]:
        return {"limit": limit}

    return test_app


async def request(
    app: FastAPI,
    path: str,
    *,
    query_string: bytes = b"",
    expect_server_exception: bool = False,
) -> tuple[int, dict[str, object]]:
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query_string,
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[Message] = []
    received_request = False

    async def receive() -> Message:
        nonlocal received_request
        if received_request:
            return {"type": "http.disconnect"}
        received_request = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    try:
        await app(scope, receive, send)
    except Exception:
        if not expect_server_exception:
            raise

    response_start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return response_start["status"], json.loads(response_body)


class ErrorHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_app = create_test_app()

    async def test_application_error_returns_structured_response(self) -> None:
        status, body = await request(self.test_app, "/known-error")

        self.assertEqual(status, 404)
        self.assertEqual(
            body,
            {
                "error": {
                    "code": "item_not_found",
                    "message": "The requested item was not found.",
                }
            },
        )

    async def test_unexpected_error_returns_generic_response(self) -> None:
        with self.assertLogs(
            "backend.app.core.error_handlers",
            level="ERROR",
        ) as captured:
            status, body = await request(
                self.test_app,
                "/unexpected-error",
                expect_server_exception=True,
            )

        self.assertEqual(status, 500)
        self.assertEqual(
            body,
            {
                "error": {
                    "code": "internal_server_error",
                    "message": "An unexpected error occurred.",
                }
            },
        )
        self.assertNotIn("internal details", json.dumps(body))
        self.assertTrue(any("Unhandled exception" in line for line in captured.output))

    async def test_invalid_request_uses_fastapi_validation_response(self) -> None:
        status, body = await request(
            self.test_app,
            "/validated",
            query_string=b"limit=0",
        )

        self.assertEqual(status, 422)
        self.assertIn("detail", body)
        self.assertNotIn("error", body)

    async def test_health_endpoints_keep_existing_responses(self) -> None:
        expected = {
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.app_version,
        }

        status, body = await request(application, "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, expected)

        status, body = await request(application, "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, expected)

    async def test_main_app_registers_central_error_handlers(self) -> None:
        self.assertIn(ApplicationError, application.exception_handlers)
        self.assertIn(Exception, application.exception_handlers)

    async def test_application_metadata_and_health_schema(self) -> None:
        self.assertEqual(application.title, settings.app_name)
        self.assertEqual(application.version, settings.app_version)
        self.assertIn(
            "HealthResponse",
            application.openapi()["components"]["schemas"],
        )

    async def test_settings_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configured = Settings(_env_file=None)

        self.assertEqual(configured.app_name, "ATLAS")
        self.assertEqual(configured.app_version, "0.1.0")
        self.assertEqual(configured.environment, "development")
        self.assertTrue(configured.debug)
        self.assertEqual(configured.log_level, "INFO")

    async def test_environment_variables_override_settings_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_NAME": "ATLAS Test",
                "APP_VERSION": "2.0.0",
                "ENVIRONMENT": "testing",
                "DEBUG": "false",
                "LOG_LEVEL": "ERROR",
            },
            clear=True,
        ):
            configured = Settings(_env_file=None)

        self.assertEqual(configured.app_name, "ATLAS Test")
        self.assertEqual(configured.app_version, "2.0.0")
        self.assertEqual(configured.environment, "testing")
        self.assertFalse(configured.debug)
        self.assertEqual(configured.log_level, "ERROR")

    async def test_configured_log_level_is_applied(self) -> None:
        configure_logging("WARNING")

        self.assertEqual(logging.getLogger().level, logging.WARNING)

    async def test_startup_initializes_logging_and_logs_startup(self) -> None:
        with self.assertLogs("backend.app.main", level="INFO") as captured:
            async with application.router.lifespan_context(application):
                self.assertEqual(
                    logging.getLogger().level,
                    logging.getLevelNamesMapping()[settings.log_level],
                )

        self.assertTrue(any("Starting ATLAS" in line for line in captured.output))
