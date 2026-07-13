"""Best-effort, unauthenticated scraper for Indeed's public job search
results page. Same caveats as jobpilot.sources.linkedin: off by default,
Indeed's ToS prohibits scraping, selectors will drift over time, and this
degrades to an empty result set rather than retrying aggressively when
blocked.
"""

import logging
import random
import time
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from jobpilot.sources.base import DEFAULT_USER_AGENT, RawJob, looks_remote

logger = logging.getLogger("jobpilot.sources.indeed")

MAX_LOCATIONS_PER_RUN = 3
MIN_DELAY_SECONDS = 3
MAX_DELAY_SECONDS = 8


def fetch_indeed_jobs(title_keywords: list[str], locations: list[str]) -> list[RawJob]:
    if not locations:
        return []

    query = title_keywords[0] if title_keywords else "software engineer"
    jobs: list[RawJob] = []

    for i, location in enumerate(locations[:MAX_LOCATIONS_PER_RUN]):
        if i > 0:
            time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
        jobs.extend(_fetch_one_location(query, location))

    return jobs


def _fetch_one_location(query: str, location: str) -> list[RawJob]:
    domain = "in.indeed.com" if "hyderabad" in location.lower() or "india" in location.lower() else "www.indeed.com"
    params = {"q": query, "l": location}
    url = f"https://{domain}/jobs?{urlencode(params)}"

    resp = httpx.get(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=20,
        follow_redirects=True,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    cards = soup.select("div.job_seen_beacon") or soup.select("td.resultContent")

    jobs: list[RawJob] = []
    for card in cards:
        try:
            title_link = card.select_one("h2.jobTitle a")
            title_span = card.select_one("h2.jobTitle span")
            company_el = card.select_one("span.companyName")
            location_el = card.select_one("div.companyLocation")
            if title_link is None or title_span is None:
                continue

            title = title_span.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else ""
            loc_text = location_el.get_text(strip=True) if location_el else location
            href = title_link.get("href", "")
            full_url = href if href.startswith("http") else f"https://{domain}{href}"

            jobs.append(
                RawJob(
                    source="indeed",
                    source_job_id=title_link.get("data-jk", ""),
                    title=title,
                    company_name=company or "Unknown",
                    location_raw=loc_text,
                    is_remote=looks_remote(loc_text),
                    url=full_url,
                )
            )
        except Exception as exc:  # noqa: BLE001 — one broken card must not drop the rest
            logger.debug("skipping unparseable Indeed card: %s", exc)
            continue

    if not jobs:
        logger.warning(
            "Indeed search for '%s' returned no parseable results — likely blocked/challenged "
            "or the page markup changed. This is expected periodically for this best-effort source.",
            location,
        )

    return jobs
