from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.integrations.google.errors import GoogleIntegrationError
from backend.app.integrations.google.models import (
    CalendarDeleteResult,
    CalendarEventList,
    FreeSlotList,
    GmailDraftResult,
    GmailMessage,
    GmailSearchResult,
    GmailSendResult,
    GoogleEvent,
)
from backend.app.integrations.google.service import GoogleApiClient
from backend.app.security.models import PermissionId, RiskLevel
from backend.app.tools.base import Tool
from backend.app.tools.errors import ToolFrameworkError
from backend.app.tools.executor import ToolExecutionService
from backend.app.tools.factory import create_tool_execution_service
from backend.app.tools.models import ToolErrorInfo
from backend.app.tools.demo import EchoTool


class GoogleTool(Tool):
    google: GoogleApiClient
    permission_id: ClassVar[str]

    def error_handler(self, error: Exception) -> ToolErrorInfo:
        if isinstance(error, GoogleIntegrationError):
            return ToolErrorInfo(code=error.code, message=error.safe_message)
        if isinstance(error, ToolFrameworkError):
            return super().error_handler(error)
        return ToolErrorInfo(
            code="google_operation_failed",
            message="The Google operation could not be completed.",
        )


class CalendarListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="primary", min_length=1, max_length=255)
    time_min: datetime
    time_max: datetime
    max_results: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarListInput":
        _validate_interval(self.time_min, self.time_max)
        return self


class CalendarGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    calendar_id: str = Field(default="primary", min_length=1, max_length=255)
    event_id: str = Field(min_length=1, max_length=1024)


class CalendarFreeSlotsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="primary", min_length=1, max_length=255)
    time_min: datetime
    time_max: datetime
    duration_minutes: int = Field(ge=15, le=480)

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarFreeSlotsInput":
        _validate_interval(self.time_min, self.time_max)
        return self


class CalendarCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="primary", min_length=1, max_length=255)
    summary: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=8000)
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarCreateInput":
        _validate_interval(self.start, self.end)
        return self


class CalendarUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="primary", min_length=1, max_length=255)
    event_id: str = Field(min_length=1, max_length=1024)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=8000)
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> "CalendarUpdateInput":
        if all(
            value is None
            for value in (self.summary, self.description, self.start, self.end)
        ):
            raise ValueError("At least one event field must be supplied.")
        if self.start is not None and self.end is not None:
            _validate_interval(self.start, self.end)
        return self


class CalendarDeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    calendar_id: str = Field(default="primary", min_length=1, max_length=255)
    event_id: str = Field(min_length=1, max_length=1024)


class CalendarListEventsTool(GoogleTool):
    name = "calendar.list_events"
    description = "Lists calendar events within a time range."
    input_schema = CalendarListInput
    output_schema = CalendarEventList
    permission_required = True
    permission_id = PermissionId.CALENDAR_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, CalendarListInput):
            raise TypeError
        return self.google.calendar_list_events(
            calendar_id=arguments.calendar_id,
            time_min=arguments.time_min.isoformat(),
            time_max=arguments.time_max.isoformat(),
            max_results=arguments.max_results,
        )


class CalendarGetEventTool(GoogleTool):
    name = "calendar.get_event"
    description = "Gets one calendar event by identifier."
    input_schema = CalendarGetInput
    output_schema = GoogleEvent
    permission_required = True
    permission_id = PermissionId.CALENDAR_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, CalendarGetInput):
            raise TypeError
        return self.google.calendar_get_event(
            calendar_id=arguments.calendar_id,
            event_id=arguments.event_id,
        )


class CalendarFindFreeSlotsTool(GoogleTool):
    name = "calendar.find_free_slots"
    description = "Finds free time intervals in a calendar range."
    input_schema = CalendarFreeSlotsInput
    output_schema = FreeSlotList
    permission_required = True
    permission_id = PermissionId.CALENDAR_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, CalendarFreeSlotsInput):
            raise TypeError
        return self.google.calendar_find_free_slots(
            calendar_id=arguments.calendar_id,
            time_min=arguments.time_min,
            time_max=arguments.time_max,
            duration_minutes=arguments.duration_minutes,
        )


class CalendarCreateEventTool(GoogleTool):
    name = "calendar.create_event"
    description = "Creates a calendar event."
    input_schema = CalendarCreateInput
    output_schema = GoogleEvent
    permission_required = True
    permission_id = PermissionId.CALENDAR_CREATE.value
    risk_level = RiskLevel.MEDIUM.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, CalendarCreateInput):
            raise TypeError
        return self.google.calendar_create_event(
            calendar_id=arguments.calendar_id,
            event={
                "summary": arguments.summary,
                "description": arguments.description,
                "start": arguments.start.isoformat(),
                "end": arguments.end.isoformat(),
            },
        )


class CalendarUpdateEventTool(GoogleTool):
    name = "calendar.update_event"
    description = "Updates specified fields of a calendar event."
    input_schema = CalendarUpdateInput
    output_schema = GoogleEvent
    permission_required = True
    permission_id = PermissionId.CALENDAR_UPDATE.value
    risk_level = RiskLevel.MEDIUM.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, CalendarUpdateInput):
            raise TypeError
        return self.google.calendar_update_event(
            calendar_id=arguments.calendar_id,
            event_id=arguments.event_id,
            changes={
                "summary": arguments.summary,
                "description": arguments.description,
                "start": arguments.start.isoformat() if arguments.start else None,
                "end": arguments.end.isoformat() if arguments.end else None,
            },
        )


class CalendarDeleteEventTool(GoogleTool):
    name = "calendar.delete_event"
    description = "Deletes a calendar event after authorization."
    input_schema = CalendarDeleteInput
    output_schema = CalendarDeleteResult
    permission_required = True
    permission_id = PermissionId.CALENDAR_DELETE.value
    risk_level = RiskLevel.HIGH.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, CalendarDeleteInput):
            raise TypeError
        return self.google.calendar_delete_event(
            calendar_id=arguments.calendar_id,
            event_id=arguments.event_id,
        )


class GmailSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=20, ge=1, le=50)


class GmailGetMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message_id: str = Field(min_length=1, max_length=1024)


class GmailCreateDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    to: str = Field(pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$", max_length=320)
    subject: str = Field(max_length=998)
    body: str = Field(min_length=1, max_length=20000)


class GmailSendInput(GmailCreateDraftInput):
    pass


class GmailReplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message_id: str = Field(min_length=1, max_length=1024)
    body: str = Field(min_length=1, max_length=20000)


class GmailSearchTool(GoogleTool):
    name = "gmail.search"
    description = "Searches Gmail and returns message identifiers."
    input_schema = GmailSearchInput
    output_schema = GmailSearchResult
    permission_required = True
    permission_id = PermissionId.GMAIL_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, GmailSearchInput):
            raise TypeError
        return self.google.gmail_search(
            query=arguments.query,
            max_results=arguments.max_results,
        )


class GmailGetMessageTool(GoogleTool):
    name = "gmail.get_message"
    description = "Gets normalized details for one Gmail message."
    input_schema = GmailGetMessageInput
    output_schema = GmailMessage
    permission_required = True
    permission_id = PermissionId.GMAIL_READ.value
    risk_level = RiskLevel.LOW.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, GmailGetMessageInput):
            raise TypeError
        return self.google.gmail_get_message(message_id=arguments.message_id)


class GmailCreateDraftTool(GoogleTool):
    name = "gmail.create_draft"
    description = "Creates a Gmail draft without sending it."
    input_schema = GmailCreateDraftInput
    output_schema = GmailDraftResult
    permission_required = True
    permission_id = PermissionId.GMAIL_DRAFT.value
    risk_level = RiskLevel.MEDIUM.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, GmailCreateDraftInput):
            raise TypeError
        return self.google.gmail_create_draft(
            to=arguments.to,
            subject=arguments.subject,
            body=arguments.body,
        )


class GmailSendTool(GoogleTool):
    name = "gmail.send"
    description = "Sends a Gmail message after authorization."
    input_schema = GmailSendInput
    output_schema = GmailSendResult
    permission_required = True
    permission_id = PermissionId.GMAIL_SEND.value
    risk_level = RiskLevel.HIGH.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, GmailSendInput):
            raise TypeError
        return self.google.gmail_send(
            to=arguments.to,
            subject=arguments.subject,
            body=arguments.body,
        )


class GmailReplyTool(GoogleTool):
    name = "gmail.reply"
    description = "Replies to a Gmail message after authorization."
    input_schema = GmailReplyInput
    output_schema = GmailSendResult
    permission_required = True
    permission_id = PermissionId.GMAIL_REPLY.value
    risk_level = RiskLevel.HIGH.value

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, GmailReplyInput):
            raise TypeError
        return self.google.gmail_reply(
            message_id=arguments.message_id,
            body=arguments.body,
        )


def create_google_tools(google: GoogleApiClient) -> list[Tool]:
    tools: list[Tool] = [
        EchoTool(),
        CalendarListEventsTool(),
        CalendarFindFreeSlotsTool(),
        CalendarGetEventTool(),
        CalendarCreateEventTool(),
        CalendarUpdateEventTool(),
        CalendarDeleteEventTool(),
        GmailSearchTool(),
        GmailGetMessageTool(),
        GmailCreateDraftTool(),
        GmailSendTool(),
        GmailReplyTool(),
    ]
    for tool in tools:
        if isinstance(tool, GoogleTool):
            tool.google = google
    return tools


def create_google_tool_service(
    google: GoogleApiClient,
) -> ToolExecutionService:
    return create_tool_execution_service(create_google_tools(google))


def _validate_interval(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Calendar event times must include a timezone.")
    if end <= start:
        raise ValueError("Calendar event end must follow its start.")
