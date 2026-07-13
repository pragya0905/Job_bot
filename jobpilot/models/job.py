from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class Job(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "dedupe_hash", name="uq_job_user_dedupe"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    source: str  # greenhouse | lever | ashby | remoteok | weworkremotely | linkedin | indeed
    source_job_id: str = ""
    title: str
    company_name: str
    location_raw: str = ""
    is_remote: bool = False
    url: str = ""
    description_text: str = ""
    posted_at: Optional[datetime] = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    dedupe_hash: str = Field(index=True)
    status: str = "new"  # new | scored | tailored | reviewed
