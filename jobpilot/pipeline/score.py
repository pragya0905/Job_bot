import logging

from sqlmodel import Session, select

from jobpilot.config import AppConfig
from jobpilot.llm.client import structured_chat
from jobpilot.llm.prompts import SCORING_SYSTEM, build_scoring_prompt
from jobpilot.models import Job, JobPreference, JobScore, ScanRun
from jobpilot.pipeline.progress import log_progress
from jobpilot.pipeline.tailor import load_profile_context
from jobpilot.schemas.llm import JobScoreOut

logger = logging.getLogger("jobpilot.score")


async def score_jobs(
    session: Session, config: AppConfig, jobs: list[Job], user_id: int, scan_run: ScanRun | None = None
) -> list[Job]:
    """Score each job against the candidate profile with the fast local
    model. Returns the subset of jobs that were successfully scored (used
    downstream to decide which ones to attempt tailoring for).
    """
    if not jobs:
        return []

    profile, profile_dict, _, _, _ = load_profile_context(session, user_id)
    if profile is None:
        logger.warning("no profile set — skipping scoring for %d jobs", len(jobs))
        return []

    preference = session.exec(select(JobPreference).where(JobPreference.user_id == user_id)).first()
    preferred_sectors = preference.preferred_sectors if preference else []
    avoid_sectors = preference.avoid_sectors if preference else []

    scored: list[Job] = []
    for i, job in enumerate(jobs, start=1):
        item_label = f"{job.title} @ {job.company_name}"
        if scan_run:
            log_progress(session, scan_run, f"Scoring ({i}/{len(jobs)}): {item_label}...", current_item=item_label)

        result = await structured_chat(
            host=config.ollama.host,
            model=config.scoring.model,
            system=SCORING_SYSTEM,
            user=build_scoring_prompt(
                profile_dict,
                job.title,
                job.company_name,
                job.location_raw,
                job.description_text,
                preferred_sectors,
                avoid_sectors,
            ),
            schema=JobScoreOut,
            temperature=config.scoring.temperature,
        )
        if result is None:
            job.status = "needs_review"
            session.add(job)
            if scan_run:
                log_progress(session, scan_run, f"  ✗ scoring failed for {item_label} — marked needs_review")
            continue

        job_score = JobScore(
            job_id=job.id,
            model_used=config.scoring.model,
            score=result.score,
            rationale=result.rationale,
            matched_skills=result.matched_skills,
            missing_requirements=result.missing_requirements,
        )
        job.status = "scored"
        session.add(job_score)
        session.add(job)
        scored.append(job)
        if scan_run:
            log_progress(session, scan_run, f"  → score={result.score}")

    session.commit()
    return scored
