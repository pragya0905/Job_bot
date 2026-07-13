import httpx

from jobpilot.sources.base import DEFAULT_USER_AGENT, RawJob, html_to_text, looks_remote


def fetch_ashby_jobs(company_name: str, client_name: str) -> list[RawJob]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{client_name}"
    resp = httpx.get(
        url,
        params={"includeCompensation": "true"},
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data.get("jobs", []):
        location = item.get("location", "")
        is_remote = bool(item.get("isRemote")) or looks_remote(location)
        description = item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml", ""))
        jobs.append(
            RawJob(
                source="ashby",
                source_job_id=str(item.get("id", "")),
                title=item.get("title", ""),
                company_name=company_name,
                location_raw=location,
                is_remote=is_remote,
                url=item.get("jobUrl") or item.get("applyUrl", ""),
                description_text=description,
            )
        )
    return jobs
