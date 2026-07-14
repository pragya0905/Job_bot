from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class Profile(SQLModel, table=True):
    """One per user — holds the candidate's structured resume content."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True)
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    summary: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProfileExperience(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id")
    entry_type: str = "experience"  # experience | internship
    company: str
    title: str
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    order_index: int = 0
    bullets: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Alternative to hand-written bullets: a raw description of what was done,
    # rewritten into bullet_count bullets per job at tailoring time. Only used
    # when non-empty — leaves the verbatim `bullets` system untouched for
    # entries that don't opt in.
    raw_description: str = ""
    bullet_count: int = 0


class ProfileProject(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id")
    name: str
    description: str = ""
    tech: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    link: str = ""
    order_index: int = 0


class ProfileEducation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id")
    school: str
    degree: str = ""
    field: str = ""
    start_date: str = ""
    end_date: str = ""
    cgpa: str = ""
    coursework: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    order_index: int = 0


class ProfileCertification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id")
    name: str
    issuer: str = ""
    date: str = ""
    credential_url: str = ""
    order_index: int = 0


class ProfileSkillCategory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id")
    category: str
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    order_index: int = 0
