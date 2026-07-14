from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ApplicationEvent(SQLModel, table=True):
    """Dated timeline for a job's application — auto-logged status changes
    plus freeform notes the user adds (interview scheduled, recruiter call,
    follow-up reminders, ...). Kept as its own append-only table rather than
    a single ApplicationStatus.notes field so the history itself is visible,
    not just the latest note."""

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    kind: str = "note"  # note | status_change
    text: str
