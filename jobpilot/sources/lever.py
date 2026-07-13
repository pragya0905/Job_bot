import httpx

from jobpilot.sources.base import DEFAULT_USER_AGENT, RawJob, html_to_text, looks_remote


def fetch_lever_jobs(company_name: str, company_slug: str) -> list[RawJob]:
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    resp = httpx.get(
        url,
        params={"mode": "json"},
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data:
        categories = item.get("categories") or {}
        location = categories.get("location", "") or item.get("country", "")
        is_remote = looks_remote(location) or (categories.get("allLocations") and any(
            looks_remote(loc) for loc in categories.get("allLocations", [])
        ))
        description = item.get("descriptionPlain") or html_to_text(item.get("description", ""))
        lists_text = "\n".join(
            f"{lst.get('text', '')}\n" + html_to_text(lst.get("content", ""))
            for lst in item.get("lists", [])
        )
        jobs.append(
            RawJob(
                source="lever",
                source_job_id=str(item.get("id", "")),
                title=item.get("text", ""),
                company_name=company_name,
                location_raw=location,
                is_remote=bool(is_remote),
                url=item.get("hostedUrl", ""),
                description_text=f"{description}\n\n{lists_text}".strip(),
            )
        )
    return jobs
