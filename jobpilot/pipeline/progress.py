from datetime import datetime

from sqlmodel import Session

from jobpilot.models import ScanRun

MAX_LOG_LINES = 300


def log_progress(session: Session, scan_run: ScanRun, message: str, *, current_item: str | None = None) -> None:
    """Append a timestamped line to this run's live log and update what's
    currently being worked on. Commits immediately so the polling
    /scan/{run_id}/status endpoint sees it right away, even mid-stage.
    """
    timestamp = datetime.utcnow().strftime("%H:%M:%S")
    lines = list(scan_run.log_lines)
    lines.append(f"[{timestamp}] {message}")
    scan_run.log_lines = lines[-MAX_LOG_LINES:]
    if current_item is not None:
        scan_run.current_item = current_item
    session.add(scan_run)
    session.commit()
