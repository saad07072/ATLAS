import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.core.error_schemas import ErrorDetail, ErrorResponse
from backend.app.core.exceptions import ApplicationError

logger = logging.getLogger(__name__)


async def application_error_handler(
    request: Request,
    exc: ApplicationError,
) -> JSONResponse:
    response = ErrorResponse(
        error=ErrorDetail(code=exc.code, message=exc.message)
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(),
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "Unhandled exception while processing %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    response = ErrorResponse(
        error=ErrorDetail(
            code="internal_server_error",
            message="An unexpected error occurred.",
        )
    )
    return JSONResponse(status_code=500, content=response.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)
