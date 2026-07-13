from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ApplicationStatus(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", unique=True)
    status: str = "not_applied"  # not_applied | applied | interviewing | rejected | offer
    applied_at: Optional[datetime] = None
    notes: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)
