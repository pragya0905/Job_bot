from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class CompanyWatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    ats_type: str  # greenhouse | lever | ashby
    ats_slug: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
