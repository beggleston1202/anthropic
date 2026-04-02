"""
Microsoft Graph API connector for Outlook email and calendar.

Auth: OAuth2 client credentials (app-only) via MSAL.
Scopes required in Azure AD app registration:
  - Mail.Read (application)
  - Calendars.Read (application)
"""
from datetime import date, datetime
import httpx
import msal

import config
from models import ActivitySource, RawActivity


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_token_cache: dict = {}


def _get_token() -> str:
    app = msal.ConfidentialClientApplication(
        client_id=config.AZURE_CLIENT_ID,
        client_credential=config.AZURE_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}",
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"MSAL token error: {result.get('error_description', result)}")
    return result["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Accept": "application/json"}


def _iso(d: date) -> str:
    return datetime(d.year, d.month, d.day).isoformat() + "Z"


def fetch_emails(date_from: date, date_to: date) -> list[RawActivity]:
    """Fetch sent emails and received emails for the date range."""
    activities: list[RawActivity] = []
    user = config.OUTLOOK_USER_EMAIL

    for folder in ("sentItems", "inbox"):
        url = (
            f"{GRAPH_BASE}/users/{user}/mailFolders/{folder}/messages"
            f"?$filter=receivedDateTime ge {_iso(date_from)} and receivedDateTime le {_iso(date_to)}"
            f"&$select=id,subject,receivedDateTime,from,toRecipients,bodyPreview"
            f"&$top=100&$orderby=receivedDateTime desc"
        )
        while url:
            resp = httpx.get(url, headers=_headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for msg in data.get("value", []):
                participants = _extract_participants(msg, folder)
                activities.append(
                    RawActivity(
                        source=ActivitySource.OUTLOOK_EMAIL,
                        external_id=msg["id"],
                        activity_date=_parse_date(msg["receivedDateTime"]),
                        subject=msg.get("subject", "(no subject)"),
                        participants=participants,
                        duration_minutes=None,
                        raw_content=f"[{folder}] {msg.get('bodyPreview', '')}",
                    )
                )
            url = data.get("@odata.nextLink")

    return activities


def fetch_calendar(date_from: date, date_to: date) -> list[RawActivity]:
    """Fetch calendar events for the date range."""
    user = config.OUTLOOK_USER_EMAIL
    url = (
        f"{GRAPH_BASE}/users/{user}/calendarView"
        f"?startDateTime={_iso(date_from)}&endDateTime={_iso(date_to)}"
        f"&$select=id,subject,start,end,attendees,bodyPreview,duration"
        f"&$top=100"
    )
    activities: list[RawActivity] = []
    while url:
        resp = httpx.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for event in data.get("value", []):
            start = datetime.fromisoformat(event["start"]["dateTime"].rstrip("Z"))
            end = datetime.fromisoformat(event["end"]["dateTime"].rstrip("Z"))
            duration_minutes = int((end - start).total_seconds() / 60)
            attendees = ", ".join(
                a["emailAddress"].get("name", a["emailAddress"].get("address", ""))
                for a in event.get("attendees", [])
            )
            activities.append(
                RawActivity(
                    source=ActivitySource.OUTLOOK_CALENDAR,
                    external_id=event["id"],
                    activity_date=start.date(),
                    subject=event.get("subject", "(no title)"),
                    participants=attendees,
                    duration_minutes=duration_minutes,
                    raw_content=event.get("bodyPreview", ""),
                )
            )
        url = data.get("@odata.nextLink")
    return activities


def _extract_participants(msg: dict, folder: str) -> str:
    if folder == "sentItems":
        return ", ".join(
            r["emailAddress"].get("name", r["emailAddress"].get("address", ""))
            for r in msg.get("toRecipients", [])
        )
    sender = msg.get("from", {}).get("emailAddress", {})
    return sender.get("name", sender.get("address", ""))


def _parse_date(ts: str) -> date:
    return datetime.fromisoformat(ts.rstrip("Z")).date()
