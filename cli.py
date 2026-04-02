"""
CLI entrypoint for the Ajax Time Tracker.

Usage:
  python cli.py backfill --start 2026-01-01 --end 2026-04-02
  python cli.py sync
  python cli.py serve
  python cli.py scheduler
"""
from datetime import date, timedelta

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Ajax Time Tracker — AI-powered billable time capture.")
console = Console()


@app.command()
def backfill(
    start: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., help="End date (YYYY-MM-DD)"),
):
    """Pull activity from all sources for a custom date range and generate time entry suggestions."""
    from scheduler import run_sync

    date_from = date.fromisoformat(start)
    date_to = date.fromisoformat(end)

    console.print(f"[bold]Starting backfill:[/bold] {date_from} → {date_to}")
    with console.status("Fetching activities and running AI classification..."):
        log = run_sync(date_from, date_to)

    if log.error:
        console.print(f"[bold red]Sync failed:[/bold red] {log.error[:500]}")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Done![/bold green]")
    console.print(f"  Activities fetched : {log.activities_fetched}")
    console.print(f"  Entries created    : {log.entries_created}")
    console.print(f"\nOpen [link=http://localhost:8000]http://localhost:8000[/link] to review.")


@app.command()
def sync():
    """Sync yesterday's activity (same as the daily scheduled job)."""
    from scheduler import run_sync

    yesterday = date.today() - timedelta(days=1)
    console.print(f"[bold]Syncing:[/bold] {yesterday}")
    with console.status("Running sync..."):
        log = run_sync(yesterday, yesterday)

    if log.error:
        console.print(f"[bold red]Sync failed:[/bold red] {log.error[:500]}")
        raise typer.Exit(code=1)

    console.print(f"[bold green]Done![/bold green] {log.entries_created} entries created.")


@app.command()
def serve():
    """Start the web dashboard."""
    import uvicorn
    import config

    console.print(f"[bold]Starting dashboard at http://localhost:{config.PORT}[/bold]")
    uvicorn.run("main:app", host="0.0.0.0", port=config.PORT, reload=False)


@app.command()
def scheduler():
    """Start the daily background scheduler + web dashboard together."""
    import uvicorn
    import config
    from scheduler import start_scheduler

    sched = start_scheduler()
    console.print(f"[bold]Scheduler started.[/bold] Daily sync at {config.DAILY_SYNC_HOUR}:00.")
    console.print(f"[bold]Dashboard:[/bold] http://localhost:{config.PORT}")
    try:
        uvicorn.run("main:app", host="0.0.0.0", port=config.PORT, reload=False)
    finally:
        sched.shutdown()


@app.command()
def status():
    """Show current entry counts from the database."""
    from sqlmodel import Session, select
    from database import engine, init_db
    from models import SuggestedEntry, EntryStatus

    init_db()
    with Session(engine) as session:
        all_entries = session.exec(select(SuggestedEntry)).all()

    table = Table(title="Time Entry Status")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    table.add_column("Hours", justify="right")

    for status_val in EntryStatus:
        subset = [e for e in all_entries if e.status == status_val]
        table.add_row(
            status_val.value.title(),
            str(len(subset)),
            f"{sum(e.hours for e in subset):.1f}",
        )

    console.print(table)


if __name__ == "__main__":
    app()
