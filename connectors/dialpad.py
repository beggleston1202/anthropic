"""
Dialpad API connector — fetches call logs.

Auth: API key (DIALPAD_API_KEY).
Docs: https://developers.dialpad.com/reference
"""
from datetime import date, datetime
import httpx

import config
from models import ActivitySource, RawActivity

DIALPAD_API = "https://dialpad.com/api/v2"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.DIALPAD_API_KEY}",
        "Accept": "application/json",
    }


def fetch_calls(date_from: date, date_to: date) -> list[RawActivity]:
    """Fetch call log for the date range."""
    activities: list[RawActivity] = []

    # Dialpad uses Unix milliseconds for date filters
    started_after = int(datetime(date_from.year, date_from.month, date_from.day).timestamp() * 1000)
    started_before = int(datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59).timestamp() * 1000)

    url = (
        f"{DIALPAD_API}/call"
        f"?started_after={started_after}&started_before={started_before}&limit=100"
    )

    while url:
        resp = httpx.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for call in data.get("items", []):
            duration_sec = call.get("duration", 0)
            duration_minutes = max(1, round(duration_sec / 60)) if duration_sec else None

            contact = call.get("contact", {}) or {}
            contact_name = contact.get("name") or call.get("external_number", "Unknown")

            direction = call.get("direction", "")
            call_type = call.get("call_type", "")

            activities.append(
                RawActivity(
                    source=ActivitySource.DIALPAD,
                    external_id=str(call["call_id"]),
                    activity_date=_ms_to_date(call.get("date_started", 0)),
                    subject=f"{direction.title()} call with {contact_name}",
                    participants=contact_name,
                    duration_minutes=duration_minutes,
                    raw_content=(
                        f"Direction: {direction}, Type: {call_type}, "
                        f"Duration: {duration_sec}s, "
                        f"Transcript: {call.get('transcription', {}).get('transcript', 'N/A')}"
                    ),
                )
            )

        cursor = data.get("cursor")
        if cursor:
            base = url.split("?")[0]
            url = f"{base}?cursor={cursor}&limit=100"
        else:
            url = None

    return activities


def _ms_to_date(ms: int) -> date:
    if not ms:
        return date.today()
    return datetime.fromtimestamp(ms / 1000).date()
