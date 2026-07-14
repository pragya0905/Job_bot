from datetime import datetime

from sqlmodel import Session

from jobpilot.models import ScanLogEntry, ScanRun


def log_progress(
    session: Session,
    scan_run: ScanRun,
    message: str,
    *,
    current_item: str | None = None,
    job_id: int | None = None,
) -> None:
    """Persist one log line for this run — permanently, with no cap, and
    optionally tagged with the specific job it concerns (scoring/tailoring
    lines pass job_id so that job's own history can be looked up directly
    later). Commits immediately so the polling /scan/{run_id}/status
    endpoint sees it right away, even mid-stage.
    """
    timestamp = datetime.utcnow().strftime("%H:%M:%S")
    entry = ScanLogEntry(scan_run_id=scan_run.id, job_id=job_id, message=f"[{timestamp}] {message}")
    session.add(entry)
    if current_item is not None:
        scan_run.current_item = current_item
    session.add(scan_run)
    session.commit()


def is_cancelled(session: Session, scan_run: ScanRun) -> bool:
    """Re-reads cancel_requested from the DB rather than the in-memory
    object, since the Cancel button is handled by a separate request/session
    that commits the flag independently of this run's long-lived session.
    Called from several different points in the pipeline (not just in a
    tight loop with a guaranteed commit right before it), so this commits
    rather than refreshes: a bare session.refresh() discards any of this
    run's own pending-but-uncommitted attribute changes (e.g. jobs_scored)
    before they're ever persisted — commit() persists them first, then
    (since this session's default expire_on_commit=True expires every
    tracked object on commit) the very next attribute read transparently
    reloads from the DB, picking up the cancel flag either way. Net effect
    is the same "see fresh cancel_requested" behavior without the silent
    data loss.
    """
    session.commit()
    return scan_run.cancel_requested
