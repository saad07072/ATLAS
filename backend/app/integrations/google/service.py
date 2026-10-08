from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote, urlencode

from pydantic import ValidationError

from backend.app.config.settings import Settings
from backend.app.integrations.google.errors import (
    GoogleIntegrationError,
    normalize_google_status,
)
from backend.app.integrations.google.models import (
    CalendarDeleteResult,
    CalendarEventList,
    FreeSlot,
    FreeSlotList,
    GmailDraftResult,
    GmailMessage,
    GmailSearchResult,
    GmailSendResult,
    GoogleEvent,
)
from backend.app.integrations.google.oauth import GoogleOAuthService
from backend.app.integrations.google.transport import HttpTransport, UrllibTransport

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


class GoogleApiClient:
    def __init__(
        self,
        oauth: GoogleOAuthService,
        settings: Settings,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self.oauth = oauth
        self.settings = settings
        self.transport = transport or UrllibTransport()

    def calendar_list_events(
        self,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        max_results: int,
    ) -> CalendarEventList:
        payload = self._request(
            "GET",
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
            query={
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        events = [
            self._event(item)
            for item in payload.get("items", [])
            if isinstance(item, dict)
        ]
        return CalendarEventList(
            events=events,
            next_page_token=payload.get("nextPageToken"),
        )

    def calendar_get_event(self, *, calendar_id: str, event_id: str) -> GoogleEvent:
        payload = self._request(
            "GET",
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events/"
            f"{quote(event_id, safe='')}",
        )
        return self._event(payload)

    def calendar_find_free_slots(
        self,
        *,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        duration_minutes: int,
    ) -> FreeSlotList:
        payload = self._request(
            "POST",
            f"{CALENDAR_API}/freeBusy",
            body={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "items": [{"id": calendar_id}],
            },
        )
        calendars = payload.get("calendars", {})
        calendar = calendars.get(calendar_id, {}) if isinstance(calendars, dict) else {}
        busy_items = calendar.get("busy", []) if isinstance(calendar, dict) else []
        busy = sorted(
            (
                self._parse_datetime(item["start"]),
                self._parse_datetime(item["end"]),
            )
            for item in busy_items
            if isinstance(item, dict) and item.get("start") and item.get("end")
        )

        slots: list[FreeSlot] = []
        cursor = time_min
        duration = timedelta(minutes=duration_minutes)
        for busy_start, busy_end in busy:
            if busy_start > cursor and busy_start - cursor >= duration:
                slots.append(FreeSlot(start=cursor, end=busy_start))
            cursor = max(cursor, busy_end)
        if time_max > cursor and time_max - cursor >= duration:
            slots.append(FreeSlot(start=cursor, end=time_max))
        return FreeSlotList(slots=slots)

    def calendar_create_event(
        self,
        *,
        calendar_id: str,
        event: dict[str, str | None],
    ) -> GoogleEvent:
        payload = self._request(
            "POST",
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
            body=self._calendar_event_body(event),
        )
        return self._event(payload)

    def calendar_update_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        changes: dict[str, str | None],
    ) -> GoogleEvent:
        fields: dict[str, Any] = {}
        for key, value in changes.items():
            if value is None:
                continue
            if key in {"start", "end"}:
                fields[key] = {"dateTime": value}
            else:
                fields[key] = value
        payload = self._request(
            "PATCH",
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events/"
            f"{quote(event_id, safe='')}",
            body=fields,
        )
        return self._event(payload)

    def calendar_delete_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
    ) -> CalendarDeleteResult:
        self._request(
            "DELETE",
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events/"
            f"{quote(event_id, safe='')}",
            allow_empty=True,
        )
        return CalendarDeleteResult(deleted=True)

    def gmail_search(
        self,
        *,
        query: str,
        max_results: int,
    ) -> GmailSearchResult:
        payload = self._request(
            "GET",
            f"{GMAIL_API}/users/me/messages",
            query={"q": query, "maxResults": max_results},
        )
        return GmailSearchResult(
            messages=[
                {
                    "id": item["id"],
                    "thread_id": item["threadId"],
                }
                for item in payload.get("messages", [])
                if isinstance(item, dict) and item.get("id") and item.get("threadId")
            ],
            next_page_token=payload.get("nextPageToken"),
        )

    def gmail_get_message(self, *, message_id: str) -> GmailMessage:
        payload = self._request(
            "GET",
            f"{GMAIL_API}/users/me/messages/{quote(message_id, safe='')}",
            query={"format": "full"},
        )
        return self._normalize_gmail_message(payload)

    def gmail_create_draft(
        self,
        *,
        to: str,
        subject: str,
        body: str,
    ) -> GmailDraftResult:
        raw = self._encoded_email(to=to, subject=subject, body=body)
        payload = self._request(
            "POST",
            f"{GMAIL_API}/users/me/drafts",
            body={"message": {"raw": raw}},
        )
        message = payload.get("message", {})
        return GmailDraftResult(
            id=payload.get("id", ""),
            message_id=message.get("id", ""),
            thread_id=message.get("threadId", ""),
        )

    def gmail_send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
    ) -> GmailSendResult:
        raw = self._encoded_email(to=to, subject=subject, body=body)
        payload = self._request(
            "POST",
            f"{GMAIL_API}/users/me/messages/send",
            body={"raw": raw},
        )
        return GmailSendResult(
            id=payload.get("id", ""),
            thread_id=payload.get("threadId", ""),
            label_ids=payload.get("labelIds", []),
        )

    def gmail_reply(self, *, message_id: str, body: str) -> GmailSendResult:
        original = self.gmail_get_message(message_id=message_id)
        headers = {
            "To": original.from_address,
            "Subject": (
                original.subject
                if original.subject.lower().startswith("re:")
                else f"Re: {original.subject}"
            ),
        }
        if original.message_id:
            headers["In-Reply-To"] = original.message_id
            headers["References"] = " ".join(
                part
                for part in (original.references, original.message_id)
                if part
            )
        raw = self._encoded_email(body=body, extra_headers=headers)
        payload = self._request(
            "POST",
            f"{GMAIL_API}/users/me/messages/send",
            body={"raw": raw, "threadId": original.thread_id},
        )
        return GmailSendResult(
            id=payload.get("id", ""),
            thread_id=payload.get("threadId", ""),
            label_ids=payload.get("labelIds", []),
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        query: dict[str, str | int] | None = None,
        body: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        if query:
            url = f"{url}?{urlencode(query)}"
        request_body = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )
        token = self.oauth.access_token()
        response = self._send(method, url, request_body, token)
        if response.status_code == 401:
            token = self.oauth.refresh_access_token().access_token
            response = self._send(method, url, request_body, token)
        if response.status_code < 200 or response.status_code >= 300:
            raise normalize_google_status(response.status_code)
        if allow_empty and response.status_code == 204:
            return {}
        try:
            payload = json.loads(response.body)
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise GoogleIntegrationError(
                "invalid_google_response",
                "Google returned an invalid response.",
            ) from None

    def _send(
        self,
        method: str,
        url: str,
        body: bytes | None,
        token: str,
    ):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers["Authorization"] = "Bearer " + token
        return self.transport.request(
            method,
            url,
            headers=headers,
            body=body,
            timeout=self.settings.google_api_timeout_seconds,
        )

    @staticmethod
    def _event(payload: dict[str, Any]) -> GoogleEvent:
        start = payload.get("start", {})
        end = payload.get("end", {})
        try:
            return GoogleEvent(
                id=payload.get("id", ""),
                summary=payload.get("summary", ""),
                description=payload.get("description"),
                start=start.get("dateTime") or start.get("date", ""),
                end=end.get("dateTime") or end.get("date", ""),
                status=payload.get("status", "confirmed"),
                html_link=payload.get("htmlLink"),
            )
        except (ValidationError, AttributeError):
            raise GoogleIntegrationError(
                "invalid_google_response",
                "Google returned an invalid event response.",
            ) from None

    @staticmethod
    def _calendar_event_body(event: dict[str, str | None]) -> dict[str, Any]:
        body: dict[str, Any] = {}
        for key, value in event.items():
            if value is None:
                continue
            if key in {"start", "end"}:
                body[key] = {"dateTime": value}
            else:
                body[key] = value
        return body

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise GoogleIntegrationError(
                "invalid_google_response",
                "Google returned an invalid time interval.",
            )
        return parsed

    @staticmethod
    def _normalize_gmail_message(payload: dict[str, Any]) -> GmailMessage:
        message_payload = payload.get("payload", {})
        headers = message_payload.get("headers", [])
        header_map = {
            item.get("name", "").lower(): item.get("value", "")
            for item in headers
            if isinstance(item, dict)
        }
        body = GoogleApiClient._extract_gmail_body(message_payload)
        try:
            return GmailMessage(
                id=payload.get("id", ""),
                thread_id=payload.get("threadId", ""),
                from_address=header_map.get("from", ""),
                to_address=header_map.get("to", ""),
                subject=header_map.get("subject", ""),
                date=header_map.get("date", ""),
                snippet=payload.get("snippet", ""),
                body=body,
                message_id=header_map.get("message-id", ""),
                references=header_map.get("references", ""),
            )
        except ValidationError:
            raise GoogleIntegrationError(
                "invalid_google_response",
                "Google returned an invalid message response.",
            ) from None

    @staticmethod
    def _extract_gmail_body(payload: dict[str, Any]) -> str:
        data = payload.get("body", {}).get("data")
        if data:
            try:
                padded = data + "=" * (-len(data) % 4)
                return base64.urlsafe_b64decode(padded).decode(
                    "utf-8",
                    errors="replace",
                )
            except (ValueError, UnicodeEncodeError):
                return ""
        for part in payload.get("parts", []):
            if isinstance(part, dict):
                body = GoogleApiClient._extract_gmail_body(part)
                if body:
                    return body
        return ""

    @staticmethod
    def _encoded_email(
        *,
        body: str,
        to: str | None = None,
        subject: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        message = EmailMessage()
        if to:
            message["To"] = to
        if subject:
            message["Subject"] = subject
        for key, value in (extra_headers or {}).items():
            message[key] = value
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
