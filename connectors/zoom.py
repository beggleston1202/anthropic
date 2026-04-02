"""
Zoom API connector — fetches meeting history.

Auth: Server-to-Server OAuth (ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET).
Docs: https://developers.zoom.us/docs/api/
"""
from datetime import date, datetime
import httpx

import config
from models import ActivitySource, RawActivity

ZOOM_API = "https://api.zoom.us/v2"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
_zoom_token: dict = {}


def _get_token() -> str:
    resp = httpx.post(
        ZOOM_TOKEN_URL,
        params={"grant_type": "account_credentials", "account_id": config.ZOOM_ACCOUNT_ID},
        auth=(config.ZOOM_CLIENT_ID, config.ZOOM_CLIENT_SECRET),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Accept": "application/json"}


def fetch_meetings(date_from: date, date_to: date) -> list[RawActivity]:
    """Fetch past meetings for the date range."""
    activities: list[RawActivity] = []

    # Use the "me" endpoint (credentials are for the attorney's account)
    url = (
        f"{ZOOM_API}/users/me/meetings"
        f"?type=past&from={date_from.isoformat()}&to={date_to.isoformat()}&page_size=100"
    )

    while url:
        resp = httpx.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for meeting in data.get("meetings", []):
            # Fetch meeting participants for richer context
            participants = _get_participants(meeting["uuid"])
            duration_minutes = meeting.get("duration", 0)

            activities.append(
                RawActivity(
                    source=ActivitySource.ZOOM,
                    external_id=str(meeting["uuid"]),
                    activity_date=_parse_date(meeting.get("start_time", "")),
                    subject=meeting.get("topic", "(Zoom Meeting)"),
                    participants=", ".join(participants) if participants else "Unknown",
                    duration_minutes=duration_minutes,
                    raw_content=(
                        f"Topic: {meeting.get('topic', '')}, "
                        f"Duration: {duration_minutes} min, "
                        f"Participants: {', '.join(participants)}"
                    ),
                )
            )

        next_token = data.get("next_page_token")
        if next_token:
            base = url.split("?")[0]
            url = f"{base}?type=past&from={date_from.isoformat()}&to={date_to.isoformat()}&page_size=100&next_page_token={next_token}"
        else:
            url = None

    return activities


def _get_participants(meeting_uuid: str) -> list[str]:
    """Fetch participant names for a past meeting."""
    try:
        resp = httpx.get(
            f"{ZOOM_API}/past_meetings/{meeting_uuid}/participants",
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        return list({p.get("name", p.get("user_email", "")) for p in resp.json().get("participants", [])})
    except Exception:
        return []


def _parse_date(ts: str) -> date:
    if not ts:
        return date.today()
    return datetime.fromisoformat(ts.rstrip("Z")).date()
