import logging

from sqlmodel import Session, select

from jobpilot.config import AppConfig
from jobpilot.llm.client import structured_chat
from jobpilot.llm.embeddings import cosine_similarity, embed_text, profile_text_for_embedding
from jobpilot.llm.prompts import SCORING_SYSTEM, build_scoring_prompt
from jobpilot.models import Job, JobPreference, JobScore, ScanRun
from jobpilot.pipeline.comp_classify import estimate_compensation
from jobpilot.pipeline.progress import is_cancelled, log_progress
from jobpilot.pipeline.tailor import load_profile_context
from jobpilot.schemas.llm import JobScoreOut

logger = logging.getLogger("jobpilot.score")

_NON_SALARY_SENTINELS = {"none", "n/a", "na", "not stated", "not specified", "unspecified", ""}
_BENEFIT_FALSE_POSITIVES = ("401k", "403b")  # digits-that-look-like-pay but are retirement plans


def clean_stated_salary(raw: str) -> str | None:
    """Ground-truth check on the model's stated_salary field before it's
    ever stored — mirrors the reconciliation pattern used everywhere else
    in this app rather than trusting the raw LLM string. Testing against
    the real model surfaced two concrete failure modes this catches: the
    literal "none" sentinel (and close variants) meaning nothing was
    stated, and confident-looking hallucinations that reference a real
    number in the JD that isn't actually a salary (e.g. "401k matching"
    getting extracted because "401" + "k" superficially resembles a pay
    figure like "150k").
    """
    if not raw:
        return None
    text = raw.strip()
    if text.lower() in _NON_SALARY_SENTINELS:
        return None
    if not any(ch.isdigit() for ch in text):
        return None
    normalized = text.lower().replace("(", "").replace(")", "")
    if any(term in normalized for term in _BENEFIT_FALSE_POSITIVES):
        return None
    return text


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

    # Opt-in extra signal: embed the profile once per batch (not once per
    # job) and reuse it — the profile doesn't change mid-scan. If the
    # embedding model isn't pulled, this fails once here rather than on
    # every job, and semantic scoring is silently skipped for the whole run.
    use_semantic = bool(preference and preference.use_semantic_scoring)
    profile_embedding = None
    if use_semantic:
        profile_embedding = await embed_text(
            config.ollama.host, config.embedding.model, profile_text_for_embedding(profile_dict)
        )
        if profile_embedding is None and scan_run:
            log_progress(
                session,
                scan_run,
                f"  ⚠ semantic scoring enabled but '{config.embedding.model}' isn't available in Ollama — skipping "
                f"(run `ollama pull {config.embedding.model}` to enable it).",
            )

    scored: list[Job] = []
    for i, job in enumerate(jobs, start=1):
        if scan_run and is_cancelled(session, scan_run):
            log_progress(session, scan_run, f"Cancelled — stopped before scoring {len(jobs) - i + 1} remaining job(s).")
            break

        item_label = f"{job.title} @ {job.company_name}"
        if scan_run:
            log_progress(
                session, scan_run, f"Scoring ({i}/{len(jobs)}): {item_label}...", current_item=item_label, job_id=job.id
            )

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
                log_progress(
                    session, scan_run, f"  ✗ scoring failed for {item_label} — marked needs_review", job_id=job.id
                )
            continue

        semantic_score = None
        if profile_embedding is not None:
            jd_embedding = await embed_text(config.ollama.host, config.embedding.model, job.description_text)
            if jd_embedding is not None:
                similarity = cosine_similarity(profile_embedding, jd_embedding)
                semantic_score = round(max(0.0, min(1.0, similarity)) * 100)

        job_score = JobScore(
            job_id=job.id,
            model_used=config.scoring.model,
            score=result.score,
            rationale=result.rationale,
            matched_skills=result.matched_skills,
            missing_requirements=result.missing_requirements,
            semantic_score=semantic_score,
        )
        job.status = "scored"
        job.stated_salary = clean_stated_salary(result.stated_salary)

        # Only worth the extra LLM call when neither source already gave us
        # a real, employer-stated figure — an estimate would just be thrown
        # away unseen otherwise (display_salary always prefers a stated one).
        if not job.stated_salary and not job.salary_raw:
            job.estimated_comp = await estimate_compensation(
                host=config.ollama.host,
                model=config.scoring.model,
                job_title=job.title,
                company_name=job.company_name,
                location=job.location_raw,
                description=job.description_text,
            )

        session.add(job_score)
        session.add(job)
        scored.append(job)
        if scan_run:
            suffix = f" (semantic={semantic_score}%)" if semantic_score is not None else ""
            if job.stated_salary:
                salary_note = f" · salary: {job.stated_salary}"
            elif job.estimated_comp:
                salary_note = f" · est. comp: ~{job.estimated_comp} (unverified)"
            else:
                salary_note = ""
            log_progress(session, scan_run, f"  → score={result.score}{suffix}{salary_note}", job_id=job.id)

    session.commit()
    return scored
