from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ScanLogEntry(SQLModel, table=True):
    """One row per log line produced during a scan — permanent (no cap,
    unlike the old capped-JSON-array-on-ScanRun approach), and optionally
    tagged with the specific job it concerns (scoring/tailoring lines) so a
    job's own history can be looked up directly instead of grepping through
    the whole scan's log by eye."""

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_run_id: int = Field(foreign_key="scanrun.id", index=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    message: str
