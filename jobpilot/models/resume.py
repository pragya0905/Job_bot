from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ResumeDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    version: int = 1
    model_used: str = ""
    summary: str = ""
    experience: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    internships: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    skills_emphasis: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    edited_manually: bool = False
    pdf_path: str = ""
    cover_letter: str = ""
    cover_letter_pdf_path: str = ""
