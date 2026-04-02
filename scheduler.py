"""
Core sync logic and APScheduler daily automation.

run_sync(date_from, date_to) is the single entry point called by:
  - cli.py (backfill / manual sync)
  - main.py (web-triggered sync via POST /sync)
  - start_scheduler() (daily automated job)
"""
from datetime import date, datetime, timedelta
import traceback

from sqlmodel import Session, select
from apscheduler.schedulers.background import BackgroundScheduler

import config
from database import engine, init_db
from models import ActivitySource, RawActivity, SuggestedEntry, SyncLog
from ai.classifier import classify_activities
from connectors.clio import get_matters

# Import connectors conditionally based on configuration
if config.outlook_configured():
    from connectors.outlook import fetch_emails, fetch_calendar
if config.basecamp_configured():
    from connectors.basecamp import fetch_activity as fetch_basecamp
if config.dialpad_configured():
    from connectors.dialpad import fetch_calls
if config.zoom_configured():
    from connectors.zoom import fetch_meetings


def run_sync(date_from: date, date_to: date) -> SyncLog:
    """
    Fetch activities from all configured sources for the given date range,
    classify them with Claude, and persist suggested entries to the database.
    """
    init_db()
    log = SyncLog(date_from=date_from, date_to=date_to)

    with Session(engine) as session:
        session.add(log)
        session.commit()
        session.refresh(log)

        try:
            # 1. Collect raw activities from every configured source
            all_activities: list[RawActivity] = []

            if config.outlook_configured():
                all_activities.extend(fetch_emails(date_from, date_to))
                all_activities.extend(fetch_calendar(date_from, date_to))

            if config.basecamp_configured():
                all_activities.extend(fetch_basecamp(date_from, date_to))

            if config.dialpad_configured():
                all_activities.extend(fetch_calls(date_from, date_to))

            if config.zoom_configured():
                all_activities.extend(fetch_meetings(date_from, date_to))

            # 2. Dedup against already-fetched activities
            existing_ids = set(
                row.external_id
                for row in session.exec(select(RawActivity)).all()
            )
            new_activities = [a for a in all_activities if a.external_id not in existing_ids]

            # 3. Persist new raw activities
            for activity in new_activities:
                session.add(activity)
            session.commit()
            # Refresh to get DB-assigned IDs
            for activity in new_activities:
                session.refresh(activity)

            log.activities_fetched = len(new_activities)

            # 4. Fetch Clio matters for AI matching
            matters = get_matters() if config.clio_configured() else []

            # 5. AI classification
            suggested = classify_activities(new_activities, matters)

            for entry in suggested:
                session.add(entry)
            session.commit()

            log.entries_created = len(suggested)
            log.finished_at = datetime.utcnow()
            session.add(log)
            session.commit()

        except Exception as exc:
            log.error = traceback.format_exc()[:2000]
            log.finished_at = datetime.utcnow()
            session.add(log)
            session.commit()
            raise

    return log


def _daily_job():
    yesterday = date.today() - timedelta(days=1)
    run_sync(yesterday, yesterday)


def start_scheduler():
    """Start the APScheduler background scheduler for daily syncs."""
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _daily_job,
        trigger="cron",
        hour=config.DAILY_SYNC_HOUR,
        minute=0,
        id="daily_sync",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
