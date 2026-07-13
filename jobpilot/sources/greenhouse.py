import httpx

from jobpilot.sources.base import DEFAULT_USER_AGENT, RawJob, html_to_text, looks_remote


def fetch_greenhouse_jobs(company_name: str, board_token: str) -> list[RawJob]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    resp = httpx.get(
        url,
        params={"content": "true"},
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name", "")
        jobs.append(
            RawJob(
                source="greenhouse",
                source_job_id=str(item.get("id", "")),
                title=item.get("title", ""),
                company_name=company_name,
                location_raw=location,
                is_remote=looks_remote(location),
                url=item.get("absolute_url", ""),
                description_text=html_to_text(item.get("content", "")),
            )
        )
    return jobs
