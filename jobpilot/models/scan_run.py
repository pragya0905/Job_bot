from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ScanRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    status: str = "running"  # running | completed | failed | cancelled
    stage: str = "collecting"  # collecting | filtering | scoring | tailoring | done
    current_item: str = ""  # what's being worked on right now, e.g. "Scoring: Backend Engineer @ Stripe"
    cancel_requested: bool = False
    # Full per-line log lives in ScanLogEntry (permanent, per-job-taggable,
    # searchable) — this table used to also carry a capped log_lines JSON
    # array directly; the underlying SQLite column still exists on rows
    # created before that migration but is no longer mapped here.
    jobs_collected: int = 0
    jobs_filtered: int = 0
    jobs_scored: int = 0
    jobs_tailored: int = 0
    error_log: str = ""
