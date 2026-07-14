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
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    dedupe_hash: str = Field(index=True)
    status: str = "new"  # new | scored | tailored | reviewed
    salary_raw: str = ""  # structured field pulled straight from a source API (Ashby/RemoteOK/Lever)
    stated_salary: Optional[str] = None  # LLM-extracted from the JD text itself during scoring — null if none stated
    # Only ever populated when stated_salary/salary_raw are both empty — a
    # static-reference-table lookup (pipeline/comp_reference.py), never an
    # LLM-generated number. Always render with an "estimated, unverified"
    # label — see Job.display_salary_is_estimate.
    estimated_comp: Optional[str] = None
    # Set for the duration of a manual "Regenerate with AI" run (the slow
    # tailoring model can take minutes) so the job detail page can show a
    # live in-progress indicator instead of the request just hanging with no
    # feedback. Always reset in a finally block regardless of outcome.
    tailoring_in_progress: bool = False

    @property
    def display_salary(self) -> str:
        """A posting can state its own pay in two different places — a
        structured API field (salary_raw) or plain text buried in the
        description (stated_salary, pulled out by the scorer) — and most
        jobs only ever populate one of the two. Falls back to a static
        reference-table estimate (clearly unverified) only when neither
        source stated a real figure. Surfaced as a single consolidated
        value so the UI doesn't show competing salary lines for what's
        conceptually the same underlying fact.
        """
        return self.stated_salary or self.salary_raw or self.estimated_comp or ""

    @property
    def display_salary_is_estimate(self) -> bool:
        """True when display_salary is falling back to the unverified
        reference-table estimate rather than a figure the posting itself
        stated — the UI must never show this without the estimate label."""
        return not (self.stated_salary or self.salary_raw) and bool(self.estimated_comp)
