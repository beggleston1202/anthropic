from datetime import datetime, date
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field


class ActivitySource(str, Enum):
    OUTLOOK_EMAIL = "outlook_email"
    OUTLOOK_CALENDAR = "outlook_calendar"
    BASECAMP = "basecamp"
    DIALPAD = "dialpad"
    ZOOM = "zoom"


class EntryStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTED = "submitted"


class RawActivity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: ActivitySource
    external_id: str  # ID from the source system (dedup key)
    activity_date: date
    subject: str
    participants: str  # comma-separated names/emails
    duration_minutes: Optional[int] = None
    raw_content: str  # full text/description from source
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class SuggestedEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    raw_activity_id: Optional[int] = Field(default=None, foreign_key="rawactivity.id")
    source: ActivitySource
    activity_date: date
    matter_id: Optional[str] = None      # Clio matter ID
    matter_name: Optional[str] = None    # Human-readable matter name
    client_name: Optional[str] = None
    hours: float = 0.0
    description: str = ""
    task_code: Optional[str] = None
    confidence: str = "low"              # high / medium / low
    ai_notes: Optional[str] = None       # Claude's internal reasoning note
    status: EntryStatus = EntryStatus.PENDING
    ajax_entry_id: Optional[str] = None  # set after successful submission
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None


class SyncLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    date_from: date
    date_to: date
    activities_fetched: int = 0
    entries_created: int = 0
    error: Optional[str] = None


class Matter(SQLModel):
    """In-memory model for Clio matters — not persisted."""
    id: str
    display_number: str
    description: str
    client_name: str
    status: str
