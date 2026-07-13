from email.utils import parsedate_to_datetime

import feedparser
import httpx

from jobpilot.sources.base import DEFAULT_USER_AGENT, RawJob, html_to_text

FEED_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"


def fetch_weworkremotely_jobs() -> list[RawJob]:
    # feedparser's built-in fetcher uses urllib, which fails TLS verification
    # in some Python installs (missing local CA bundle wiring) — fetch with
    # httpx (bundles certifi) and hand feedparser the raw bytes instead.
    resp = httpx.get(FEED_URL, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=20)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    jobs = []
    for entry in feed.entries:
        title = entry.get("title", "")
        company_name, _, job_title = title.partition(": ")
        if not job_title:
            job_title = title
            company_name = ""

        posted_at = None
        if entry.get("published"):
            try:
                posted_at = parsedate_to_datetime(entry["published"])
            except (TypeError, ValueError):
                posted_at = None

        jobs.append(
            RawJob(
                source="weworkremotely",
                source_job_id=entry.get("id", "") or entry.get("link", ""),
                title=job_title,
                company_name=company_name or "Unknown",
                location_raw="Remote",
                is_remote=True,
                url=entry.get("link", ""),
                description_text=html_to_text(entry.get("summary", "")),
                posted_at=posted_at,
            )
        )
    return jobs
