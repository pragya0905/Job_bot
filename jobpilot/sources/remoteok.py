from datetime import datetime

import httpx

from jobpilot.sources.base import DEFAULT_USER_AGENT, RawJob, html_to_text


def fetch_remoteok_jobs() -> list[RawJob]:
    resp = httpx.get(
        "https://remoteok.com/api",
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            # element 0 is a legal/attribution notice, not a job — skip it
            continue
        posted_at = None
        if item.get("date"):
            try:
                posted_at = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        # salary_min/salary_max are annual USD integers, present on only a
        # small minority of listings — 0 (not missing) is RemoteOK's way of
        # saying "not provided", so treat 0 as absent rather than a real figure.
        salary_min, salary_max = item.get("salary_min") or 0, item.get("salary_max") or 0
        salary_raw = f"${salary_min:,} - ${salary_max:,}" if salary_min and salary_max else ""

        jobs.append(
            RawJob(
                source="remoteok",
                source_job_id=str(item.get("id", "")),
                title=item.get("position", ""),
                company_name=item.get("company", ""),
                location_raw=item.get("location", "") or "Remote",
                is_remote=True,
                url=item.get("url", "") or item.get("apply_url", ""),
                description_text=html_to_text(item.get("description", "")),
                posted_at=posted_at,
                salary_raw=salary_raw,
            )
        )
    return jobs
