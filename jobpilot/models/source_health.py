from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SourceHealth(SQLModel, table=True):
    """One row per (user, collector source) — tracks whether each job board
    / ATS company feed is actually working, so a source that's started
    silently failing (blocked, renamed slug, API change) is visible instead
    of just quietly returning fewer jobs forever."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    source_key: str = Field(index=True)  # e.g. "greenhouse:openai", "remoteok", "linkedin"
    display_name: str = ""
    last_attempt_at: datetime = Field(default_factory=datetime.utcnow)
    last_success_at: Optional[datetime] = None
    last_job_count: int = 0
    last_error: str = ""
    consecutive_failures: int = 0
