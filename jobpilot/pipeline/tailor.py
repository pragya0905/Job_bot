import difflib
import logging

from sqlmodel import Session, select

from jobpilot.config import AppConfig
from jobpilot.llm.client import structured_chat
from jobpilot.llm.prompts import TAILORING_SYSTEM, build_tailoring_prompt, profile_to_dict
from jobpilot.models import (
    Job,
    JobScore,
    Profile,
    ProfileCertification,
    ProfileEducation,
    ProfileExperience,
    ProfileProject,
    ProfileSkillCategory,
    ResumeDraft,
    ScanRun,
)
from jobpilot.pdf.render import render_resume_pdf
from jobpilot.pipeline.progress import log_progress
from jobpilot.schemas.llm import SkillCategoryOut, TailoredResumeOut

logger = logging.getLogger("jobpilot.tailor")

# Below this similarity, a returned bullet doesn't reliably map back to any
# original profile bullet and gets treated as fabricated rather than reworded.
BULLET_MATCH_CUTOFF = 0.5


def _verify_bullets(model_bullets: list[str], original_bullets: list[str]) -> list[str]:
    """Local models have been observed to corrupt a word mid-bullet even at
    temperature 0 ("Redis-backed" -> "Redis-blcked", "serverless" ->
    "serverlan") or insert words that were never there. Wording is not
    something the model is trusted to reproduce faithfully, so every
    returned bullet is mapped back to its closest original profile bullet by
    similarity and the VERBATIM original text is used — never the model's
    own text. This makes bullet corruption structurally impossible: the
    model can only choose which bullets to include and in what order.
    """
    if not original_bullets:
        return []
    remaining = list(original_bullets)
    verified: list[str] = []
    for bullet in model_bullets:
        match = difflib.get_close_matches(bullet, remaining, n=1, cutoff=BULLET_MATCH_CUTOFF)
        if match:
            verified.append(match[0])
            remaining.remove(match[0])
    if not verified:
        # Nothing the model returned mapped back to real content — fall back
        # to every original bullet in original order rather than show none.
        return list(original_bullets)
    return verified


def _reconcile_skills(result_skills: list[SkillCategoryOut], profile_dict: dict) -> list[dict]:
    """Local models have also been observed to invent a "category" that's
    actually commentary bleeding into the JSON (e.g. category name literally
    " Hyper-relevant to SDET role") instead of reusing the profile's real
    category names. Category names are copied verbatim from the profile;
    only which skills to include/reorder within a real category is trusted
    to the model.
    """
    known = {cat["category"].strip().lower(): cat for cat in profile_dict.get("skills", [])}
    reconciled: list[dict] = []
    for cat_out in result_skills:
        known_cat = known.get(cat_out.category.strip().lower())
        if known_cat is None:
            logger.warning("dropping invented skills category from model output: %r", cat_out.category)
            continue
        known_skills_lower = {s.lower(): s for s in known_cat["skills"]}
        filtered_skills = [known_skills_lower[s.lower()] for s in cat_out.skills if s.lower() in known_skills_lower]
        if filtered_skills:
            reconciled.append({"category": known_cat["category"], "skills": filtered_skills})
    if not reconciled:
        # Model output didn't survive reconciliation — fall back to the
        # profile's full skill list rather than show an empty section.
        return [{"category": c["category"], "skills": c["skills"]} for c in profile_dict.get("skills", [])]
    return reconciled


def load_profile_context(session: Session, user_id: int):
    profile = session.exec(select(Profile).where(Profile.user_id == user_id)).first()
    if profile is None:
        return None, None, None, None, None

    experience = session.exec(
        select(ProfileExperience).where(ProfileExperience.profile_id == profile.id)
    ).all()
    projects = session.exec(
        select(ProfileProject).where(ProfileProject.profile_id == profile.id)
    ).all()
    education = session.exec(
        select(ProfileEducation).where(ProfileEducation.profile_id == profile.id)
    ).all()
    certifications = session.exec(
        select(ProfileCertification).where(ProfileCertification.profile_id == profile.id)
    ).all()
    skill_categories = session.exec(
        select(ProfileSkillCategory).where(ProfileSkillCategory.profile_id == profile.id)
    ).all()

    profile_dict = profile_to_dict(
        profile, list(experience), list(projects), list(education), list(certifications), list(skill_categories)
    )
    project_dicts = [{"name": p.name, "description": p.description, "tech": p.tech} for p in projects]
    education_dicts = [
        {"school": e.school, "degree": e.degree, "field": e.field, "start_date": e.start_date, "end_date": e.end_date}
        for e in education
    ]
    certification_dicts = [
        {"name": c.name, "issuer": c.issuer, "date": c.date, "credential_url": c.credential_url}
        for c in certifications
    ]
    return profile, profile_dict, project_dicts, education_dicts, certification_dicts


def _reconcile_experience_internships(result: TailoredResumeOut, profile_dict: dict) -> tuple[list[dict], list[dict]]:
    """Reconcile the model's experience/internship output against the
    profile's own ground truth.

    Three independent failure modes observed from local-model output, all
    fixed here rather than by prompting alone:
    1. An entry gets misfiled into the wrong list, or duplicated into both —
       resolved by keying on (company, title) against the profile's own
       lists rather than trusting the model's bucketing.
    2. Fields that were never supposed to be "tailored" in the first place —
       company, title, location, dates — occasionally come back corrupted
       (a typo'd word, a stray inserted character) even at temperature 0.
       Only `bullets` is genuinely LLM-authored content (reordered/reworded
       per the prompt); company/title/location/dates are copied verbatim
       from the profile here, so corruption of those fields is structurally
       impossible regardless of what the model outputs.
    3. The model sometimes omits an entire entry it decides is irrelevant
       (observed: internships silently dropped for some jobs, kept for
       others, with no consistency). Every entry in the profile is
       force-included at the end — the model can reorder/re-curate bullets
       within an entry, but can never make a whole role or internship
       disappear from the resume.
    """
    internship_lookup = {(e["company"], e["title"]): e for e in profile_dict.get("internships", [])}
    experience_lookup = {(e["company"], e["title"]): e for e in profile_dict.get("experience", [])}
    model_internship_keys = {(e.company, e.title) for e in result.internships}

    experience_by_key: dict[tuple[str, str], dict] = {}
    internships_by_key: dict[tuple[str, str], dict] = {}

    for entry in list(result.experience) + list(result.internships):
        key = (entry.company, entry.title)
        if key in internship_lookup:
            ground_truth = internship_lookup[key]
            internships_by_key[key] = {**ground_truth, "bullets": _verify_bullets(entry.bullets, ground_truth["bullets"])}
        elif key in experience_lookup:
            ground_truth = experience_lookup[key]
            experience_by_key[key] = {**ground_truth, "bullets": _verify_bullets(entry.bullets, ground_truth["bullets"])}
        else:
            # Not a recognized profile entry (shouldn't happen given the
            # anti-fabrication instruction) — keep it wherever the model put
            # it, with its own fields, rather than silently dropping content.
            bucket = internships_by_key if key in model_internship_keys else experience_by_key
            bucket[key] = entry.model_dump()

    # Force-include any profile entry the model left out entirely, with its
    # full original bullet list (no model curation happened for it).
    for key, ground_truth in experience_lookup.items():
        experience_by_key.setdefault(key, dict(ground_truth))
    for key, ground_truth in internship_lookup.items():
        internships_by_key.setdefault(key, dict(ground_truth))

    return list(experience_by_key.values()), list(internships_by_key.values())


async def _generate_draft(
    session: Session,
    config: AppConfig,
    job: Job,
    profile,
    profile_dict: dict,
    project_dicts: list[dict],
    education_dicts: list[dict],
    certification_dicts: list[dict],
    scan_run: ScanRun | None = None,
) -> ResumeDraft | None:
    item_label = f"{job.title} @ {job.company_name}"
    if scan_run:
        log_progress(session, scan_run, f"Tailoring: {item_label}...", current_item=item_label)

    result = await structured_chat(
        host=config.ollama.host,
        model=config.tailoring.model,
        system=TAILORING_SYSTEM,
        user=build_tailoring_prompt(profile_dict, job.title, job.company_name, job.location_raw, job.description_text),
        schema=TailoredResumeOut,
        temperature=config.tailoring.temperature,
        # Tailoring calls are the slowest and most prone to repetition-loop
        # runaway on this hardware (~1 tok/s observed for gemma4:26b) — cap
        # retries tighter than the default so one bad job can't eat 90+ min.
        max_attempts=2,
    )
    if result is None:
        logger.warning("tailoring failed for job %s after retries — leaving unhandled", job.id)
        if scan_run:
            log_progress(session, scan_run, f"  ✗ tailoring failed for {item_label}")
        return None

    experience_dicts, internship_dicts = _reconcile_experience_internships(result, profile_dict)
    skills_emphasis_dicts = _reconcile_skills(result.skills_emphasis, profile_dict)

    prior_versions = session.exec(select(ResumeDraft).where(ResumeDraft.job_id == job.id)).all()
    next_version = max((d.version for d in prior_versions), default=0) + 1

    draft = ResumeDraft(
        job_id=job.id,
        version=next_version,
        model_used=config.tailoring.model,
        summary=result.summary,
        experience=experience_dicts,
        internships=internship_dicts,
        skills_emphasis=skills_emphasis_dicts,
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)

    pdf_path = config.resume_dir_abs_path / f"job_{job.id}_v{draft.version}.pdf"
    render_resume_pdf(
        profile=profile,
        summary=draft.summary,
        experience=draft.experience,
        internships=draft.internships,
        skills_emphasis=draft.skills_emphasis,
        projects=project_dicts,
        education=education_dicts,
        certifications=certification_dicts,
        output_path=pdf_path,
    )
    draft.pdf_path = str(pdf_path)
    job.status = "tailored"
    session.add(draft)
    session.add(job)
    session.commit()
    session.refresh(draft)
    if scan_run:
        log_progress(session, scan_run, f"  → draft v{draft.version} ready for {item_label}")
    return draft


async def tailor_strong_matches(
    session: Session, config: AppConfig, scored_jobs: list[Job], user_id: int, scan_run: ScanRun | None = None
) -> list[ResumeDraft]:
    """Generate a tailored resume draft + PDF for every job that cleared the
    configured score threshold, using the slower/better local model.
    """
    if not scored_jobs:
        return []

    profile, profile_dict, project_dicts, education_dicts, certification_dicts = load_profile_context(
        session, user_id
    )
    if profile is None:
        return []

    drafts: list[ResumeDraft] = []
    for job in scored_jobs:
        job_score = session.exec(select(JobScore).where(JobScore.job_id == job.id)).first()
        if job_score is None or job_score.score is None or job_score.score < config.tailoring.score_threshold:
            continue
        draft = await _generate_draft(
            session, config, job, profile, profile_dict, project_dicts, education_dicts, certification_dicts, scan_run
        )
        if draft is not None:
            drafts.append(draft)

    return drafts


async def tailor_one_job(session: Session, config: AppConfig, job: Job, user_id: int) -> ResumeDraft | None:
    """Regenerate a tailored draft for a single job — used by the dashboard's
    'Regenerate with AI' button, independent of the score threshold since the
    user is explicitly asking for it.
    """
    profile, profile_dict, project_dicts, education_dicts, certification_dicts = load_profile_context(
        session, user_id
    )
    if profile is None:
        return None
    return await _generate_draft(
        session, config, job, profile, profile_dict, project_dicts, education_dicts, certification_dicts
    )
