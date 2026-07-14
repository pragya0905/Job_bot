import logging
from datetime import datetime

from sqlmodel import Session, select

from jobpilot.config import AppConfig, get_config
from jobpilot.db import get_session
from jobpilot.llm.client import unload_model
from jobpilot.models import Job, JobPreference, ScanRun
from jobpilot.pipeline.collect import collect_all
from jobpilot.pipeline.filter import passes_filters, search_locations_for
from jobpilot.pipeline.progress import is_cancelled, log_progress

logger = logging.getLogger("jobpilot.runner")


def collect_and_filter(session: Session, config: AppConfig, scan_run: ScanRun) -> list[Job]:
    """Collect raw jobs from all enabled sources, apply the keyword/location
    filter, and persist genuinely new postings (deduped by hash, scoped to
    this scan's user). Returns the list of newly-inserted Job rows.
    """
    user_id = scan_run.user_id
    preference = session.exec(select(JobPreference).where(JobPreference.user_id == user_id)).first()
    search_locations = search_locations_for(config.filters, preference)

    log_progress(
        session,
        scan_run,
        f"Starting collection... (LinkedIn/Indeed will search: {', '.join(search_locations) or '(none configured)'})",
    )
    raw_jobs, errors = collect_all(session, config, user_id, scan_run, search_locations=search_locations)
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

    existing_jobs_by_hash = {
        job.dedupe_hash: job
        for job in session.exec(select(Job).where(Job.user_id == user_id)).all()
    }
    now = datetime.utcnow()
    new_jobs: list[Job] = []
    reseen_count = 0
    for raw in filtered:
        dedupe_hash = raw.dedupe_hash
        existing = existing_jobs_by_hash.get(dedupe_hash)
        if existing is not None:
            # Still showing up in a fresh collection pass — bump last_seen_at
            # so staleness (computed from how long it's been since a job was
            # last seen at all) doesn't fire for postings that are still live.
            existing.last_seen_at = now
            session.add(existing)
            reseen_count += 1
            continue
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
            collected_at=now,
            last_seen_at=now,
            dedupe_hash=dedupe_hash,
            status="new",
            salary_raw=raw.salary_raw,
        )
        session.add(job)
        existing_jobs_by_hash[dedupe_hash] = job
        new_jobs.append(job)

    session.commit()
    for job in new_jobs:
        session.refresh(job)

    log_progress(
        session,
        scan_run,
        f"{len(new_jobs)} of those are new (not already collected before); "
        f"{reseen_count} already-known posting(s) are still live.",
    )
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

            if is_cancelled(session, scan_run):
                log_progress(session, scan_run, "Cancelled after collection — skipping scoring and tailoring.")
                scan_run.status = "cancelled"
                return

            # Score every unscored job for this user, not just this run's new
            # arrivals — covers jobs left over from an interrupted previous
            # run, and also retries jobs stuck in needs_review from a prior
            # scoring failure (a flaky LLM call otherwise loses them for good,
            # since nothing else ever revisits that status).
            unscored_jobs = session.exec(
                select(Job).where(Job.user_id == user_id, Job.status.in_(["new", "needs_review"]))
            ).all()

            from jobpilot.pipeline.score import score_jobs

            scan_run.stage = "scoring"
            log_progress(session, scan_run, f"Scoring {len(unscored_jobs)} jobs against your profile...")
            scored = await score_jobs(session, config, unscored_jobs, user_id, scan_run)
            scan_run.jobs_scored = len(scored)

            if is_cancelled(session, scan_run):
                log_progress(session, scan_run, "Cancelled after scoring — skipping tailoring.")
                scan_run.status = "cancelled"
                await unload_model(config.ollama.host, config.scoring.model)
                return

            # Tailor every scored-but-not-yet-tailored job above threshold for
            # this user, not just this run's batch — same reasoning as scoring.
            pending_tailoring = session.exec(
                select(Job).where(Job.user_id == user_id, Job.status == "scored")
            ).all()

            from jobpilot.pipeline.tailor import get_score_threshold, tailor_strong_matches

            threshold = get_score_threshold(session, config, user_id)
            scan_run.stage = "tailoring"
            log_progress(
                session,
                scan_run,
                f"Tailoring drafts for jobs scoring ≥{threshold} ({len(pending_tailoring)} candidates)...",
            )
            tailored = await tailor_strong_matches(session, config, pending_tailoring, user_id, scan_run)
            scan_run.jobs_tailored = len(tailored)

            if is_cancelled(session, scan_run):
                scan_run.status = "cancelled"
                await unload_model(config.ollama.host, config.tailoring.model)
            else:
                scan_run.stage = "done"
                scan_run.status = "completed"
                log_progress(session, scan_run, "Scan complete.", current_item="")
        except Exception as exc:  # noqa: BLE001 — surface the failure in the UI, don't crash the process
            logger.exception("scan run %s failed", scan_run_id)
            scan_run.status = "failed"
            scan_run.error_log = (scan_run.error_log + "\n" if scan_run.error_log else "") + f"FATAL: {exc}"
            log_progress(session, scan_run, f"FAILED: {exc}", current_item="")
        finally:
            scan_run.current_item = ""
            scan_run.finished_at = datetime.utcnow()
            session.add(scan_run)
            session.commit()
