"""
Claude AI-powered time entry classifier.

For each RawActivity, sends a structured prompt to claude-sonnet-4-6
and receives a suggested time entry with matter assignment, description,
hours, task code, and confidence level.
"""
import json
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

Respond ONLY with valid JSON, no commentary."""

CLASSIFY_TEMPLATE = """Analyze this activity and suggest a time entry.

ACTIVITY:
Source: {source}
Date: {activity_date}
Subject: {subject}
Participants: {participants}
Duration: {duration}
Content: {content}

ACTIVE MATTERS (ID | Matter Number | Client | Description):
{matters}

Respond with JSON:
{{
  "billable": true,
  "matter_id": "<Clio matter ID from the list above, or null if cannot determine>",
  "matter_name": "<client + short matter description>",
  "client_name": "<client name>",
  "hours": <decimal, e.g. 0.3>,
  "description": "<professional billing narrative in past tense, specific to this activity>",
  "task_code": "<UTBMS code>",
  "confidence": "<high|medium|low>",
  "notes": "<brief reason for matter assignment or any uncertainty>"
}}"""


def classify_activities(
    activities: list[RawActivity],
    matters: list[Matter],
) -> list[SuggestedEntry]:
    """
    Run each RawActivity through Claude and return SuggestedEntry objects.
    Non-billable activities are skipped.
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

    prompt = CLASSIFY_TEMPLATE.format(
        source=activity.source.value.replace("_", " ").title(),
        activity_date=activity.activity_date.isoformat(),
        subject=activity.subject,
        participants=activity.participants or "N/A",
        duration=duration_str,
        content=activity.raw_content[:1000],  # cap to keep tokens reasonable
        matters=matters_text,
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the response if wrapped in markdown
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            return None

    if not data.get("billable", True):
        return None

    return SuggestedEntry(
        raw_activity_id=activity.id,
        source=activity.source,
        activity_date=activity.activity_date,
        matter_id=data.get("matter_id"),
        matter_name=data.get("matter_name"),
        client_name=data.get("client_name"),
        hours=float(data.get("hours", 0.1)),
        description=data.get("description", ""),
        task_code=data.get("task_code"),
        confidence=data.get("confidence", "low"),
        ai_notes=data.get("notes"),
    )
