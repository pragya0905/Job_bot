import logging
from datetime import datetime

from sqlmodel import Session, select

from jobpilot.config import AppConfig, get_config
from jobpilot.db import get_session
from jobpilot.models import Job, JobPreference, ScanRun
from jobpilot.pipeline.collect import collect_all
from jobpilot.pipeline.filter import passes_filters
from jobpilot.pipeline.progress import log_progress

logger = logging.getLogger("jobpilot.runner")


def collect_and_filter(session: Session, config: AppConfig, scan_run: ScanRun) -> list[Job]:
    """Collect raw jobs from all enabled sources, apply the keyword/location
    filter, and persist genuinely new postings (deduped by hash, scoped to
    this scan's user). Returns the list of newly-inserted Job rows.
    """
    user_id = scan_run.user_id
    preference = session.exec(select(JobPreference).where(JobPreference.user_id == user_id)).first()

    log_progress(session, scan_run, "Starting collection...")
    raw_jobs, errors = collect_all(session, config, user_id, scan_run)
    scan_run.jobs_collected = len(raw_jobs)
    if errors:
        scan_run.error_log = "\n".join(errors)

    filtered = [job for job in raw_jobs if passes_filters(job, config.filters, preference)]
    scan_run.jobs_filtered = len(filtered)
    scan_run.stage = "filtering"
    log_progress(
        session,
        scan_run,
        f"Filtered {len(raw_jobs)} collected down to {len(filtered)} matching title/location criteria.",
    )

    existing_hashes = set(session.exec(select(Job.dedupe_hash).where(Job.user_id == user_id)).all())
    new_jobs: list[Job] = []
    for raw in filtered:
        dedupe_hash = raw.dedupe_hash
        if dedupe_hash in existing_hashes:
            continue
        existing_hashes.add(dedupe_hash)
        job = Job(
            user_id=user_id,
            source=raw.source,
            source_job_id=raw.source_job_id,
            title=raw.title,
            company_name=raw.company_name,
            location_raw=raw.location_raw,
            is_remote=raw.is_remote,
            url=raw.url,
            description_text=raw.description_text,
            posted_at=raw.posted_at,
            collected_at=datetime.utcnow(),
            dedupe_hash=dedupe_hash,
            status="new",
        )
        session.add(job)
        new_jobs.append(job)

    session.commit()
    for job in new_jobs:
        session.refresh(job)

    log_progress(session, scan_run, f"{len(new_jobs)} of those are new (not already collected before).")
    return new_jobs


async def run_scan(scan_run_id: int, include_linkedin: bool = False, include_indeed: bool = False) -> None:
    """Entry point used by both the CLI and the FastAPI background task.

    Runs the full collect -> filter -> score -> tailor pipeline for one
    ScanRun. Async because scoring/tailoring make many local-LLM calls via
    ollama.AsyncClient — used directly as a FastAPI BackgroundTasks target,
    or via asyncio.run() from the CLI.

    include_linkedin/include_indeed let the Run Scan page opt into the
    fragile best-effort scrapers for a single run without editing
    config.yaml's persisted (off-by-default) toggle.
    """
    config = get_config().model_copy(deep=True)
    if include_linkedin:
        config.sources.linkedin.enabled = True
    if include_indeed:
        config.sources.indeed.enabled = True

    with get_session() as session:
        scan_run = session.get(ScanRun, scan_run_id)
        if scan_run is None:
            raise ValueError(f"ScanRun {scan_run_id} not found")

        try:
            collect_and_filter(session, config, scan_run)
            user_id = scan_run.user_id

            # Score every unscored job for this user, not just this run's new
            # arrivals — covers jobs left over from an interrupted previous run.
            unscored_jobs = session.exec(
                select(Job).where(Job.user_id == user_id, Job.status == "new")
            ).all()

            from jobpilot.pipeline.score import score_jobs

            scan_run.stage = "scoring"
            log_progress(session, scan_run, f"Scoring {len(unscored_jobs)} jobs against your profile...")
            scored = await score_jobs(session, config, unscored_jobs, user_id, scan_run)
            scan_run.jobs_scored = len(scored)

            # Tailor every scored-but-not-yet-tailored job above threshold for
            # this user, not just this run's batch — same reasoning as scoring.
            pending_tailoring = session.exec(
                select(Job).where(Job.user_id == user_id, Job.status == "scored")
            ).all()

            from jobpilot.pipeline.tailor import tailor_strong_matches

            scan_run.stage = "tailoring"
            log_progress(
                session,
                scan_run,
                f"Tailoring drafts for jobs scoring ≥{config.tailoring.score_threshold} "
                f"({len(pending_tailoring)} candidates)...",
            )
            tailored = await tailor_strong_matches(session, config, pending_tailoring, user_id, scan_run)
            scan_run.jobs_tailored = len(tailored)

            scan_run.stage = "done"
            scan_run.status = "completed"
            log_progress(session, scan_run, "Scan complete.", current_item="")
        except Exception as exc:  # noqa: BLE001 — surface the failure in the UI, don't crash the process
            logger.exception("scan run %s failed", scan_run_id)
            scan_run.status = "failed"
            scan_run.error_log = (scan_run.error_log + "\n" if scan_run.error_log else "") + f"FATAL: {exc}"
            log_progress(session, scan_run, f"FAILED: {exc}", current_item="")
        finally:
            scan_run.finished_at = datetime.utcnow()
            session.add(scan_run)
            session.commit()
