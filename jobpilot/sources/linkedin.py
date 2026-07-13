"""Best-effort, unauthenticated scraper for LinkedIn's public job search
results page.

IMPORTANT — read before enabling: LinkedIn's User Agreement prohibits
automated scraping, including of publicly visible pages. This module is
off by default (see config.yaml `sources.linkedin.enabled`) and exists as
an opportunistic bonus source, not a dependable pipeline leg:

- No login, no cookies, no CAPTCHA solving. If LinkedIn blocks or challenges
  the request, this logs a warning and returns whatever it already parsed
  (possibly nothing) rather than retrying aggressively.
- Sequential requests only, with a random delay between them, capped to a
  small number of location queries per run.
- CSS selectors below target LinkedIn's public search-results markup as of
  when this was written. That markup changes periodically without notice —
  expect this to need re-tuning every so often.
"""

import logging
import random
import time
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from jobpilot.sources.base import DEFAULT_USER_AGENT, RawJob, looks_remote

logger = logging.getLogger("jobpilot.sources.linkedin")

SEARCH_URL = "https://www.linkedin.com/jobs/search/"
MAX_LOCATIONS_PER_RUN = 3
MIN_DELAY_SECONDS = 3
MAX_DELAY_SECONDS = 8


def fetch_linkedin_jobs(title_keywords: list[str], locations: list[str]) -> list[RawJob]:
    if not locations:
        return []

    query = " OR ".join(title_keywords[:3]) if title_keywords else "software engineer"
    jobs: list[RawJob] = []

    for i, location in enumerate(locations[:MAX_LOCATIONS_PER_RUN]):
        if i > 0:
            time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
        jobs.extend(_fetch_one_location(query, location))

    return jobs


def _fetch_one_location(query: str, location: str) -> list[RawJob]:
    params = {"keywords": query, "location": location}
    url = f"{SEARCH_URL}?{urlencode(params)}"

    resp = httpx.get(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=20,
        follow_redirects=True,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    cards = soup.select("div.base-card") or soup.select("li")

    jobs: list[RawJob] = []
    for card in cards:
        try:
            title_el = card.select_one(".base-search-card__title")
            company_el = card.select_one(".base-search-card__subtitle")
            location_el = card.select_one(".job-search-card__location")
            link_el = card.select_one("a.base-card__full-link") or card.select_one("a")
            if title_el is None or link_el is None:
                continue

            title = title_el.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else ""
            loc_text = location_el.get_text(strip=True) if location_el else location
            href = link_el.get("href", "")

            jobs.append(
                RawJob(
                    source="linkedin",
                    source_job_id=href.split("?")[0].rstrip("/").rsplit("-", 1)[-1] if href else "",
                    title=title,
                    company_name=company or "Unknown",
                    location_raw=loc_text,
                    is_remote=looks_remote(loc_text),
                    url=href.split("?")[0],
                )
            )
        except Exception as exc:  # noqa: BLE001 — one broken card must not drop the rest
            logger.debug("skipping unparseable LinkedIn card: %s", exc)
            continue

    if not jobs:
        logger.warning(
            "LinkedIn search for '%s' returned no parseable results — likely blocked/challenged "
            "or the page markup changed. This is expected periodically for this best-effort source.",
            location,
        )

    return jobs
