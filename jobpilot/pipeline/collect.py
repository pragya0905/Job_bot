import logging

from sqlmodel import Session, select

from jobpilot.config import AppConfig
from jobpilot.models import CompanyWatch, ScanRun
from jobpilot.pipeline.progress import log_progress
from jobpilot.sources.ashby import fetch_ashby_jobs
from jobpilot.sources.base import RawJob
from jobpilot.sources.greenhouse import fetch_greenhouse_jobs
from jobpilot.sources.lever import fetch_lever_jobs
from jobpilot.sources.remoteok import fetch_remoteok_jobs
from jobpilot.sources.weworkremotely import fetch_weworkremotely_jobs

logger = logging.getLogger("jobpilot.collect")

ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse_jobs,
    "lever": fetch_lever_jobs,
    "ashby": fetch_ashby_jobs,
}


def collect_all(
    session: Session, config: AppConfig, user_id: int, scan_run: ScanRun | None = None
) -> tuple[list[RawJob], list[str]]:
    """Collect raw jobs from every enabled source.

    Each source is isolated in a try/except so one flaky source (a blocked
    scraper, a down API) never aborts the whole scan — failures are
    collected as human-readable messages for the ScanRun error log.
    """
    jobs: list[RawJob] = []
    errors: list[str] = []

    companies = session.exec(
        select(CompanyWatch).where(CompanyWatch.user_id == user_id, CompanyWatch.enabled)
    ).all()
    for company in companies:
        fetcher = ATS_FETCHERS.get(company.ats_type)
        if fetcher is None:
            errors.append(f"{company.name}: unsupported ats_type '{company.ats_type}'")
            continue
        if scan_run:
            log_progress(session, scan_run, f"Collecting from {company.name} ({company.ats_type})...", current_item=company.name)
        try:
            company_jobs = fetcher(company.name, company.ats_slug)
            jobs.extend(company_jobs)
            if scan_run:
                log_progress(session, scan_run, f"  → {len(company_jobs)} postings from {company.name}")
        except Exception as exc:  # noqa: BLE001 — one bad source must not kill the scan
            logger.warning("collector failed for %s (%s): %s", company.name, company.ats_type, exc)
            errors.append(f"{company.name} ({company.ats_type}): {exc}")
            if scan_run:
                log_progress(session, scan_run, f"  ✗ {company.name} failed: {exc}")

    if config.sources.remoteok.enabled:
        if scan_run:
            log_progress(session, scan_run, "Collecting from RemoteOK...", current_item="RemoteOK")
        try:
            remoteok_jobs = fetch_remoteok_jobs()
            jobs.extend(remoteok_jobs)
            if scan_run:
                log_progress(session, scan_run, f"  → {len(remoteok_jobs)} postings from RemoteOK")
        except Exception as exc:  # noqa: BLE001
            logger.warning("remoteok collector failed: %s", exc)
            errors.append(f"remoteok: {exc}")
            if scan_run:
                log_progress(session, scan_run, f"  ✗ RemoteOK failed: {exc}")

    if config.sources.weworkremotely.enabled:
        if scan_run:
            log_progress(session, scan_run, "Collecting from We Work Remotely...", current_item="We Work Remotely")
        try:
            wwr_jobs = fetch_weworkremotely_jobs()
            jobs.extend(wwr_jobs)
            if scan_run:
                log_progress(session, scan_run, f"  → {len(wwr_jobs)} postings from We Work Remotely")
        except Exception as exc:  # noqa: BLE001
            logger.warning("weworkremotely collector failed: %s", exc)
            errors.append(f"weworkremotely: {exc}")
            if scan_run:
                log_progress(session, scan_run, f"  ✗ We Work Remotely failed: {exc}")

    if config.sources.linkedin.enabled:
        if scan_run:
            log_progress(session, scan_run, "Collecting from LinkedIn (best-effort)...", current_item="LinkedIn")
        try:
            from jobpilot.sources.linkedin import fetch_linkedin_jobs

            linkedin_jobs = fetch_linkedin_jobs(config.filters.title_keywords, config.filters.locations)
            jobs.extend(linkedin_jobs)
            if scan_run:
                log_progress(session, scan_run, f"  → {len(linkedin_jobs)} postings from LinkedIn")
        except Exception as exc:  # noqa: BLE001
            logger.warning("linkedin collector failed: %s", exc)
            errors.append(f"linkedin (best-effort): {exc}")
            if scan_run:
                log_progress(session, scan_run, f"  ✗ LinkedIn failed/blocked: {exc}")

    if config.sources.indeed.enabled:
        if scan_run:
            log_progress(session, scan_run, "Collecting from Indeed (best-effort)...", current_item="Indeed")
        try:
            from jobpilot.sources.indeed import fetch_indeed_jobs

            indeed_jobs = fetch_indeed_jobs(config.filters.title_keywords, config.filters.locations)
            jobs.extend(indeed_jobs)
            if scan_run:
                log_progress(session, scan_run, f"  → {len(indeed_jobs)} postings from Indeed")
        except Exception as exc:  # noqa: BLE001
            logger.warning("indeed collector failed: %s", exc)
            errors.append(f"indeed (best-effort): {exc}")
            if scan_run:
                log_progress(session, scan_run, f"  ✗ Indeed failed/blocked: {exc}")

    return jobs, errors
