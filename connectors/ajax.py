"""
Ajax legal billing REST API client.

Submits approved time entries to Ajax.
The exact endpoint paths and payload schema should be confirmed
from your firm's Ajax API documentation.
"""
from datetime import date
import httpx

import config
from models import SuggestedEntry


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.AJAX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_timekeepers() -> list[dict]:
    """Fetch available timekeepers from Ajax."""
    resp = httpx.get(
        f"{config.AJAX_BASE_URL}/timekeepers",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("data", resp.json())


def create_time_entry(entry: SuggestedEntry) -> str:
    """
    POST an approved time entry to Ajax.
    Returns the Ajax-assigned entry ID.

    NOTE: Adjust the payload keys to match your firm's Ajax API schema.
    Common field names are included; verify against your API docs.
    """
    payload = {
        "timekeeper_id": config.AJAX_TIMEKEEPER_ID,
        "matter_id": entry.matter_id,
        "date": entry.activity_date.isoformat(),
        "hours": entry.hours,
        "description": entry.description,
        "task_code": entry.task_code,
    }

    resp = httpx.post(
        f"{config.AJAX_BASE_URL}/time_entries",
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    # Most REST APIs return the created resource; try common ID field names
    return str(data.get("id") or data.get("entry_id") or data.get("data", {}).get("id", ""))


def submit_batch(entries: list[SuggestedEntry]) -> dict[int, str]:
    """
    Submit a list of approved entries.
    Returns a mapping of entry.id → ajax_entry_id (or error string).
    """
    results: dict[int, str] = {}
    for entry in entries:
        try:
            ajax_id = create_time_entry(entry)
            results[entry.id] = ajax_id
        except httpx.HTTPStatusError as exc:
            results[entry.id] = f"ERROR: {exc.response.status_code} {exc.response.text[:200]}"
        except Exception as exc:
            results[entry.id] = f"ERROR: {exc}"
    return results
