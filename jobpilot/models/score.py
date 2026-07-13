from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class JobScore(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", unique=True)
    model_used: str = ""
    score: Optional[int] = None
    rationale: str = ""
    matched_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    missing_requirements: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    scored_at: datetime = Field(default_factory=datetime.utcnow)
