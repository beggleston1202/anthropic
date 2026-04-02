"""
Clio Manage connector — fetches active matters and clients.

Auth: OAuth2 access token (CLIO_ACCESS_TOKEN).
Docs: https://app.clio.com/api/v4/documentation
"""
import httpx

import config
from models import Matter


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.CLIO_ACCESS_TOKEN}",
        "Accept": "application/json",
    }


def get_matters() -> list[Matter]:
    """
    Fetch all open matters from Clio.
    Returns a list of Matter objects used by the AI classifier for matching.
    """
    matters: list[Matter] = []
    url = (
        f"{config.CLIO_BASE_URL}/matters"
        f"?status=open&fields=id,display_number,description,client{{name}}&limit=200"
    )

    while url:
        resp = httpx.get(url, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for m in data.get("data", []):
            client = m.get("client") or {}
            matters.append(
                Matter(
                    id=str(m["id"]),
                    display_number=m.get("display_number", ""),
                    description=m.get("description", ""),
                    client_name=client.get("name", "Unknown Client"),
                    status="open",
                )
            )

        # Clio uses cursor-based pagination via meta.paging.next
        paging = data.get("meta", {}).get("paging", {})
        url = paging.get("next") or None

    return matters


def format_for_prompt(matters: list[Matter]) -> str:
    """Format the matter list as a compact string for inclusion in the Claude prompt."""
    lines = []
    for m in matters:
        lines.append(f"- ID:{m.id} | {m.display_number} | {m.client_name} | {m.description[:80]}")
    return "\n".join(lines)
