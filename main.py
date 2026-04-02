"""
FastAPI web dashboard for reviewing and submitting time entries.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

import config
from database import engine, get_session, init_db
from models import EntryStatus, SuggestedEntry, SyncLog
from connectors import ajax

app = FastAPI(title="Ajax Time Tracker")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    pending = session.exec(select(SuggestedEntry).where(SuggestedEntry.status == EntryStatus.PENDING)).all()
    approved = session.exec(select(SuggestedEntry).where(SuggestedEntry.status == EntryStatus.APPROVED)).all()
    rejected = session.exec(select(SuggestedEntry).where(SuggestedEntry.status == EntryStatus.REJECTED)).all()
    submitted = session.exec(select(SuggestedEntry).where(SuggestedEntry.status == EntryStatus.SUBMITTED)).all()

    recent_syncs = session.exec(
        select(SyncLog).order_by(SyncLog.started_at.desc()).limit(5)  # type: ignore[arg-type]
    ).all()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "pending_count": len(pending),
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "submitted_count": len(submitted),
            "approved_hours": round(sum(e.hours for e in approved), 1),
            "submitted_hours": round(sum(e.hours for e in submitted), 1),
            "recent_syncs": recent_syncs,
        },
    )


# ── Review ─────────────────────────────────────────────────────────────────────

@app.get("/review", response_class=HTMLResponse)
def review_list(
    request: Request,
    status: str = "pending",
    page: int = 1,
    session: Session = Depends(get_session),
):
    page_size = 20
    offset = (page - 1) * page_size
    status_enum = EntryStatus(status) if status in EntryStatus._value2member_map_ else EntryStatus.PENDING

    entries = session.exec(
        select(SuggestedEntry)
        .where(SuggestedEntry.status == status_enum)
        .order_by(SuggestedEntry.activity_date.desc())  # type: ignore[arg-type]
        .offset(offset)
        .limit(page_size)
    ).all()

    total = len(session.exec(select(SuggestedEntry).where(SuggestedEntry.status == status_enum)).all())

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "entries": entries,
            "status": status,
            "page": page,
            "total": total,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        },
    )


@app.post("/review/{entry_id}/approve")
def approve_entry(entry_id: int, session: Session = Depends(get_session)):
    entry = session.get(SuggestedEntry, entry_id)
    if entry:
        entry.status = EntryStatus.APPROVED
        entry.reviewed_at = datetime.utcnow()
        session.add(entry)
        session.commit()
    return RedirectResponse("/review?status=pending", status_code=303)


@app.post("/review/{entry_id}/reject")
def reject_entry(entry_id: int, session: Session = Depends(get_session)):
    entry = session.get(SuggestedEntry, entry_id)
    if entry:
        entry.status = EntryStatus.REJECTED
        entry.reviewed_at = datetime.utcnow()
        session.add(entry)
        session.commit()
    return RedirectResponse("/review?status=pending", status_code=303)


@app.post("/review/{entry_id}/edit")
def edit_entry(
    entry_id: int,
    matter_id: str = Form(""),
    matter_name: str = Form(""),
    hours: float = Form(...),
    description: str = Form(...),
    task_code: str = Form(""),
    session: Session = Depends(get_session),
):
    entry = session.get(SuggestedEntry, entry_id)
    if entry:
        entry.matter_id = matter_id or entry.matter_id
        entry.matter_name = matter_name or entry.matter_name
        entry.hours = hours
        entry.description = description
        entry.task_code = task_code or entry.task_code
        entry.status = EntryStatus.APPROVED
        entry.reviewed_at = datetime.utcnow()
        session.add(entry)
        session.commit()
    return RedirectResponse("/review?status=pending", status_code=303)


# ── Submit to Ajax ─────────────────────────────────────────────────────────────

@app.post("/submit")
def submit_approved(session: Session = Depends(get_session)):
    approved = session.exec(
        select(SuggestedEntry).where(SuggestedEntry.status == EntryStatus.APPROVED)
    ).all()

    if not approved:
        return RedirectResponse("/review?status=approved", status_code=303)

    results = ajax.submit_batch(list(approved))

    for entry in approved:
        ajax_id = results.get(entry.id, "")
        if ajax_id.startswith("ERROR"):
            # Leave as approved so the attorney can retry
            continue
        entry.status = EntryStatus.SUBMITTED
        entry.ajax_entry_id = ajax_id
        session.add(entry)

    session.commit()
    return RedirectResponse("/?submitted=1", status_code=303)


# ── Settings / Manual Sync ─────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request, "config": config})


@app.post("/sync")
def manual_sync(
    date_from: str = Form(...),
    date_to: str = Form(...),
):
    """Trigger a sync for a custom date range (runs in the background)."""
    from scheduler import run_sync
    import threading

    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)
    threading.Thread(target=run_sync, args=(d_from, d_to), daemon=True).start()
    return RedirectResponse("/?syncing=1", status_code=303)
