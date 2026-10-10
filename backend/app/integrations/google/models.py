from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field


class GoogleCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(min_length=1, repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    token_type: str = "Bearer"
    expires_at: datetime
    scopes: list[str] = Field(default_factory=list)

    def is_expired(self, *, leeway_seconds: int = 60) -> bool:
        return self.expires_at <= datetime.now(timezone.utc) + timedelta(
            seconds=leeway_seconds
        )


class GoogleConnectionStatus(BaseModel):
    configured: bool
    connected: bool


class OAuthTokenResponse(BaseModel):
    access_token: str = Field(min_length=1, repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    expires_in: int = Field(gt=0)
    token_type: str = "Bearer"
    scope: str = ""


class GoogleEvent(BaseModel):
    id: str = Field(min_length=1)
    summary: str = ""
    description: str | None = None
    start: str
    end: str
    status: str = "confirmed"
    html_link: str | None = None


class CalendarEventList(BaseModel):
    events: list[GoogleEvent]
    next_page_token: str | None = None


class FreeSlot(BaseModel):
    start: datetime
    end: datetime


class FreeSlotList(BaseModel):
    slots: list[FreeSlot]


class GmailMessageSummary(BaseModel):
    id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    snippet: str = ""


class GmailSearchResult(BaseModel):
    messages: list[GmailMessageSummary]
    next_page_token: str | None = None


class GmailMessage(BaseModel):
    id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    from_address: str = ""
    to_address: str = ""
    subject: str = ""
    date: str = ""
    snippet: str = ""
    body: str = ""
    message_id: str = ""
    references: str = ""


class GmailDraftResult(BaseModel):
    id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    thread_id: str = ""


class GmailSendResult(BaseModel):
    id: str = Field(min_length=1)
    thread_id: str = ""
    label_ids: list[str] = Field(default_factory=list)


class CalendarDeleteResult(BaseModel):
    deleted: bool
