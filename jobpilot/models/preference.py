from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class JobPreference(SQLModel, table=True):
    """One per user — search priorities layered on top of the technical
    title-keyword pre-filter: how strict to be about location, and which
    sectors to prioritize/deprioritize when scoring (soft signal, not a
    hard filter, since sector isn't reliably present in raw job postings)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True)
    location_mode: str = "specific_or_remote"  # remote_only | specific_or_remote | any
    preferred_locations: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    preferred_sectors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    avoid_sectors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
