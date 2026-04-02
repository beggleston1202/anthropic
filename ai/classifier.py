"""
Claude AI-powered time entry classifier.

For each RawActivity, sends a prompt to claude-sonnet-4-6 using forced tool_choice
so the response is always structured JSON (no fragile text parsing). The system
prompt and matter list are marked for prompt caching to reduce API costs ~90%
across large backfill batches.
"""
from datetime import date

import anthropic

import config
from models import ActivitySource, RawActivity, SuggestedEntry
from connectors.clio import format_for_prompt, Matter

SYSTEM_PROMPT = """You are a legal billing assistant for a family law attorney at a private law firm.
Your job is to analyze activities (emails, calls, meetings, messages) and produce accurate billable time entries.

Guidelines:
- Family law task codes (use UTBMS codes where appropriate):
  L110 = Fact investigation/development
  L120 = Analysis/strategy
  L160 = Settlement/negotiation
  L190 = Other case assessment
  L210 = Pleadings
  L310 = Written discovery
  L320 = Document production
  L330 = Depositions
  L340 = Expert discovery
  L410 = Fact witnesses
  L420 = Expert witnesses
  L430 = Written motions/briefs
  L510 = Trial preparation
  L520 = Trial/hearing
  L610 = Appellate work
  A101 = Plan and prepare for (general)
  A102 = Research
  A103 = Draft/revise
  A104 = Review/analyze
  A105 = Communicate (in firm)
  A106 = Communicate (with client)
  A107 = Communicate (other outside counsel)
  A108 = Communicate (other external)

- Time increments: round up to nearest 0.1 hour (6 minutes)
- Minimum billing: 0.1 hours for any billable communication
- Phone calls: use actual duration rounded up to nearest 0.1 hour
- Emails: typical range 0.1–0.3 hours depending on complexity
- Meetings/hearings: use actual duration
- Be conservative — if an activity clearly cannot be billed (spam, internal admin, personal), set billable=false
- Write descriptions in professional past tense: "Reviewed and responded to...", "Attended conference call re..."
- Never invent facts; base descriptions only on the provided activity content"""

# Tool definition forces Claude to return structured output — no text parsing needed.
TIME_ENTRY_TOOL = {
    "name": "create_time_entry",
    "description": "Record a billable time entry for the attorney's legal billing system.",
    "input_schema": {
        "type": "object",
        "properties": {
            "billable": {
                "type": "boolean",
                "description": "False if this activity is clearly non-billable (spam, personal, internal admin).",
            },
            "matter_id": {
                "type": ["string", "null"],
                "description": "Clio matter ID from the active matters list, or null if cannot determine.",
            },
            "matter_name": {"type": "string", "description": "Client name + short matter description."},
            "client_name": {"type": "string"},
            "hours": {
                "type": "number",
                "description": "Billable hours rounded to nearest 0.1 (e.g. 0.3).",
            },
            "description": {
                "type": "string",
                "description": "Professional billing narrative in past tense, max 200 characters.",
            },
            "task_code": {"type": "string", "description": "UTBMS task code, e.g. L120, A106."},
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Confidence in the matter assignment.",
            },
            "notes": {
                "type": "string",
                "description": "Brief internal note explaining matter assignment or any uncertainty.",
            },
        },
        "required": [
            "billable", "matter_name", "client_name", "hours",
            "description", "task_code", "confidence", "notes",
        ],
    },
}

ACTIVITY_TEMPLATE = """Analyze this activity and produce a time entry.

Source: {source}
Date: {activity_date}
Subject: {subject}
Participants: {participants}
Duration: {duration}
Content: {content}

ACTIVE MATTERS (ID | Matter Number | Client | Description):
{matters}"""


def classify_activities(
    activities: list[RawActivity],
    matters: list[Matter],
) -> list[SuggestedEntry]:
    """
    Run each RawActivity through Claude and return SuggestedEntry objects.
    Non-billable activities are skipped.

    The system prompt and matter list are sent with cache_control so that
    repeated calls within a batch reuse the cached prefix (reduces cost ~90%).
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    matters_text = format_for_prompt(matters)
    entries: list[SuggestedEntry] = []

    for activity in activities:
        result = _classify_one(client, activity, matters_text)
        if result:
            entries.append(result)

    return entries


def _classify_one(
    client: anthropic.Anthropic,
    activity: RawActivity,
    matters_text: str,
) -> SuggestedEntry | None:
    duration_str = (
        f"{activity.duration_minutes} minutes"
        if activity.duration_minutes
        else "unknown"
    )

    # Build a cacheable prefix block (system prompt + matter list) so that the
    # large constant context is only processed once per batch by the API.
    cacheable_prefix = (
        SYSTEM_PROMPT
        + "\n\nACTIVE MATTERS (ID | Matter Number | Client | Description):\n"
        + matters_text
    )

    user_content = ACTIVITY_TEMPLATE.format(
        source=activity.source.value.replace("_", " ").title(),
        activity_date=activity.activity_date.isoformat(),
        subject=activity.subject,
        participants=activity.participants or "N/A",
        duration=duration_str,
        content=activity.raw_content[:1000],
        matters=matters_text,
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": cacheable_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[TIME_ENTRY_TOOL],
        tool_choice={"type": "tool", "name": "create_time_entry"},
        messages=[{"role": "user", "content": user_content}],
    )

    # With tool_choice forced, the response is always a tool_use block.
    tool_block = next(
        (b for b in message.content if b.type == "tool_use"),
        None,
    )
    if tool_block is None:
        return None

    data = tool_block.input

    if not data.get("billable", True):
        return None

    return SuggestedEntry(
        raw_activity_id=activity.id,
        source=activity.source,
        activity_date=activity.activity_date,
        matter_id=data.get("matter_id"),
        matter_name=data.get("matter_name", ""),
        client_name=data.get("client_name", ""),
        hours=float(data.get("hours", 0.1)),
        description=data.get("description", ""),
        task_code=data.get("task_code"),
        confidence=data.get("confidence", "low"),
        ai_notes=data.get("notes"),
    )
