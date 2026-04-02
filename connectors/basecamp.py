"""
Basecamp API v3 connector.

Auth: Personal access token (BASECAMP_ACCESS_TOKEN).
Fetches: pings (direct messages), project activity for the attorney.

Basecamp API docs: https://github.com/basecamp/bc3-api
"""
from datetime import date, datetime
import httpx

import config
from models import ActivitySource, RawActivity

BASECAMP_API = "https://3.basecampapi.com"
USER_AGENT = "AjaxTimeTracker (contact@yourfirm.com)"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.BASECAMP_ACCESS_TOKEN}",
        "User-Agent": USER_AGENT,
    }


def fetch_activity(date_from: date, date_to: date) -> list[RawActivity]:
    """Fetch pings and project events for the configured date range."""
    activities: list[RawActivity] = []
    account_id = config.BASECAMP_ACCOUNT_ID

    # --- Pings (direct messages) ---
    url = f"{BASECAMP_API}/{account_id}/buckets.json"
    # Fetch projects (buckets) first to enumerate them
    projects = _paginate(url)
    for project in projects:
        project_id = project["id"]
        project_name = project.get("name", "")

        # Message board activity
        for recording in _get_recordings(account_id, project_id, date_from, date_to):
            activities.append(
                RawActivity(
                    source=ActivitySource.BASECAMP,
                    external_id=str(recording["id"]),
                    activity_date=_parse_date(recording.get("created_at", "")),
                    subject=f"[{project_name}] {recording.get('title', recording.get('content', '')[:80])}",
                    participants=recording.get("creator", {}).get("name", ""),
                    duration_minutes=None,
                    raw_content=recording.get("content", recording.get("title", "")),
                )
            )

    # --- Personal activity feed ---
    activity_url = f"{BASECAMP_API}/{account_id}/events.json?since={date_from.isoformat()}"
    for event in _paginate(activity_url):
        event_date = _parse_date(event.get("created_at", ""))
        if event_date > date_to:
            continue
        activities.append(
            RawActivity(
                source=ActivitySource.BASECAMP,
                external_id=f"event-{event['id']}",
                activity_date=event_date,
                subject=event.get("action", "") + ": " + event.get("title", ""),
                participants=event.get("creator", {}).get("name", ""),
                duration_minutes=None,
                raw_content=str(event.get("details", "")),
            )
        )

    return _dedup(activities)


def _get_recordings(account_id: str, project_id: int, date_from: date, date_to: date) -> list[dict]:
    """Fetch message board recordings (comments, todos) for a project."""
    results = []
    url = f"{BASECAMP_API}/{account_id}/buckets/{project_id}/recordings.json?type=Comment&sort=created_at&direction=desc"
    for item in _paginate(url):
        item_date = _parse_date(item.get("created_at", ""))
        if item_date < date_from:
            break
        if item_date <= date_to:
            results.append(item)
    return results


def _paginate(url: str) -> list[dict]:
    results = []
    while url:
        resp = httpx.get(url, headers=_headers(), timeout=30)
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            results.extend(data.get("recordings", []))
        # Basecamp uses Link header for pagination
        link = resp.headers.get("Link", "")
        url = _next_link(link)
    return results


def _next_link(link_header: str) -> str:
    for part in link_header.split(","):
        if 'rel="next"' in part:
            return part.split(";")[0].strip().strip("<>")
    return ""


def _parse_date(ts: str) -> date:
    if not ts:
        return date.today()
    return datetime.fromisoformat(ts.rstrip("Z")).date()


def _dedup(activities: list[RawActivity]) -> list[RawActivity]:
    seen: set[str] = set()
    unique = []
    for a in activities:
        if a.external_id not in seen:
            seen.add(a.external_id)
            unique.append(a)
    return unique
