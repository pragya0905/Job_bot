import hashlib
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 JobPilot/0.1 (personal job scan tool)"
)


class RawJob(BaseModel):
    source: str
    source_job_id: str = ""
    title: str
    company_name: str
    location_raw: str = ""
    is_remote: bool = False
    url: str = ""
    description_text: str = ""
    posted_at: Optional[datetime] = None
    salary_raw: str = ""

    @property
    def dedupe_hash(self) -> str:
        normalized = re.sub(
            r"\s+", " ", f"{self.title}|{self.company_name}|{self.location_raw}".lower()
        ).strip()
        return hashlib.sha256(normalized.encode()).hexdigest()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def looks_remote(location: str) -> bool:
    return "remote" in (location or "").lower()
