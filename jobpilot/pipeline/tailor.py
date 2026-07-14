import difflib
import logging
import re

from sqlmodel import Session, select

from jobpilot.config import AppConfig
from jobpilot.date_utils import resume_entry_sort_key
from jobpilot.llm.client import structured_chat
from jobpilot.llm.prompts import (
    BULLET_GENERATION_SYSTEM,
    TAILORING_SYSTEM,
    build_bullet_generation_prompt,
    build_tailoring_prompt,
    profile_to_dict,
)
from jobpilot.models import (
    Job,
    JobPreference,
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
from jobpilot.pdf.render import render_cover_letter_pdf, render_resume_pdf
from jobpilot.pipeline.progress import is_cancelled, log_progress
from jobpilot.schemas.llm import GeneratedBulletsOut, SkillCategoryOut, TailoredResumeOut

logger = logging.getLogger("jobpilot.tailor")

# Below this similarity, a returned bullet doesn't reliably map back to any
# original profile bullet and gets treated as fabricated rather than reworded.
BULLET_MATCH_CUTOFF = 0.5

# Enforced here in Python rather than as a schema maxLength constraint —
# that constraint is what broke Ollama's grammar compiler for this schema.
COVER_LETTER_MAX_LENGTH = 3000

# The rendered PDF adds its own greeting ("Dear {Company} Hiring Team,") and
# its own closing/signature block, and the prompt now tells the model not to
# write either — but local models don't reliably follow that instruction, so
# any line matching these patterns is stripped structurally rather than
# trusted to just not appear. Matched against the first/last non-empty line
# only, not searched for mid-paragraph.
_SALUTATION_RE = re.compile(r"^(dear|to whom it may concern|hello|hi)\b.*,?\s*$", re.IGNORECASE)
_SIGNOFF_RE = re.compile(
    r"^(sincerely|best regards|kind regards|warm regards|warmly|regards|best|yours truly|"
    r"yours sincerely|respectfully)\s*,?\s*$",
    re.IGNORECASE,
)


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


_BULLET_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")


def _verify_generated_bullets(bullets: list[str], raw_description: str) -> list[str]:
    """Same digit-grounding idea as score.py's clean_stated_salary, adapted
    to catch an invented metric/percentage in a generated bullet rather than
    a hallucinated salary figure: any number in a bullet that doesn't appear
    anywhere in the raw description means the model added a fact that isn't
    there, and the whole bullet is dropped rather than shown unverified.
    Tested against real model output including dates/durations mixed with a
    genuine metric (2023, 4 engineers, 6 months, 30%) — legitimate numbers
    pass through untouched, only genuinely absent ones get rejected. Note:
    this can't catch two real source numbers being swapped between facts
    (e.g. team size and duration transposed) — only outright invention.
    """
    source_numbers = set(_BULLET_NUMBER_RE.findall(raw_description))
    verified = []
    for bullet in bullets:
        bullet_numbers = set(_BULLET_NUMBER_RE.findall(bullet))
        if bullet_numbers - source_numbers:
            logger.warning("dropping generated bullet with unverifiable number: %r", bullet)
            continue
        verified.append(bullet)
    return verified


async def _generate_bullets_from_description(
    config: AppConfig, raw_description: str, bullet_count: int, job_title: str, description: str
) -> list[str]:
    """Constrained-rewrite path for profile entries that opted out of
    hand-written bullets (ProfileExperience.raw_description set): a
    dedicated call, separate from the main tailoring call, so the existing
    verbatim-bullet flow stays completely untouched for entries that didn't
    opt in. Falls back to the raw description itself (verbatim, so zero
    fabrication risk) if generation fails outright or every bullet gets
    rejected by the guardrail — an entry should never end up with zero
    bullets on the rendered resume.
    """
    if not raw_description.strip() or bullet_count <= 0:
        return []
    result = await structured_chat(
        host=config.ollama.host,
        model=config.tailoring.model,
        system=BULLET_GENERATION_SYSTEM,
        user=build_bullet_generation_prompt(raw_description, bullet_count, job_title, description),
        schema=GeneratedBulletsOut,
        temperature=config.tailoring.temperature,
        max_attempts=2,
    )
    bullets = _verify_generated_bullets(result.bullets[:bullet_count], raw_description) if result else []
    return bullets or [raw_description.strip()]


def _profile_dict_for_main_tailoring(profile_dict: dict) -> dict:
    """Entries in raw-description mode have no `bullets` for the main
    tailoring call to select/reorder from — leaving them in would contradict
    its "every entry must keep at least one bullet" instruction and risk the
    model fabricating one just to satisfy it. They're excluded here; the
    existing "force-include profile entries the model didn't return" step in
    _reconcile_experience_internships already picks them back up afterward
    with their ground-truth (empty) ``bullets``, which then get filled by
    _generate_bullets_from_description in _generate_draft.
    """
    filtered = dict(profile_dict)
    for key in ("experience", "internships"):
        filtered[key] = [e for e in profile_dict.get(key, []) if not e.get("raw_description")]
    return filtered


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


def _strip_salutation_and_signoff(cover_letter: str) -> str:
    """Remove a leading greeting line and/or trailing closing/signature
    lines the model wrote despite being told the rendered letter already
    adds both — otherwise the PDF shows two salutations ("Dear Microsoft
    Hiring Team," right next to the model's own "Dear Hiring Team,") and
    two sign-offs stacked on top of each other.
    """
    paragraphs = [p.strip() for p in cover_letter.strip().splitlines() if p.strip()]
    if not paragraphs:
        return cover_letter.strip()

    if _SALUTATION_RE.match(paragraphs[0]):
        paragraphs = paragraphs[1:]

    # A sign-off is sometimes its own line ("Sincerely,") immediately
    # followed by a name line (the model's own signature) — if either of
    # the last two lines is a sign-off phrase, cut there and drop everything
    # from that point on, not just the sign-off word itself.
    for i in (len(paragraphs) - 1, len(paragraphs) - 2):
        if 0 <= i < len(paragraphs) and _SIGNOFF_RE.match(paragraphs[i]):
            paragraphs = paragraphs[:i]
            break

    return "\n\n".join(paragraphs)


def get_score_threshold(session: Session, config: AppConfig, user_id: int) -> int:
    """Per-user auto-tailor threshold, editable on the Preferences page, with
    config.yaml's value as the fallback for users who haven't saved a
    preference row yet (e.g. never visited Preferences)."""
    preference = session.exec(select(JobPreference).where(JobPreference.user_id == user_id)).first()
    if preference is not None:
        return preference.score_threshold
    return config.tailoring.score_threshold


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
        {
            "school": e.school,
            "degree": e.degree,
            "field": e.field,
            "start_date": e.start_date,
            "end_date": e.end_date,
            "cgpa": e.cgpa,
            "coursework": e.coursework,
        }
        for e in education
    ]
    certification_dicts = [
        {"name": c.name, "issuer": c.issuer, "date": c.date, "credential_url": c.credential_url}
        for c in certifications
    ]
    return profile, profile_dict, project_dicts, education_dicts, certification_dicts


def _reconcile_experience_internships(
    result: TailoredResumeOut, profile_dict: dict
) -> tuple[list[dict], list[dict], list[str]]:
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
    # full original bullet list (no model curation happened for it). Also
    # recorded as labels so callers can log exactly which entries needed
    # this — a job whose tailoring silently dropped a role is worth knowing
    # about even though the final draft is correct either way.
    omitted_by_model: list[str] = []
    for key, ground_truth in experience_lookup.items():
        if key not in experience_by_key and not ground_truth.get("raw_description"):
            omitted_by_model.append(f"{ground_truth['company']} — {ground_truth['title']}")
        experience_by_key.setdefault(key, dict(ground_truth))
    for key, ground_truth in internship_lookup.items():
        if key not in internships_by_key and not ground_truth.get("raw_description"):
            omitted_by_model.append(f"{ground_truth['company']} — {ground_truth['title']} (internship)")
        internships_by_key.setdefault(key, dict(ground_truth))

    # Model output order (and the order profile-omitted entries get appended
    # in) isn't guaranteed chronological — sort explicitly so the stored
    # draft and the web edit UI show the same reverse-chronological order as
    # the rendered PDF, not just whatever order the model happened to return.
    sorted_experience = sorted(experience_by_key.values(), key=resume_entry_sort_key, reverse=True)
    sorted_internships = sorted(internships_by_key.values(), key=resume_entry_sort_key, reverse=True)
    return sorted_experience, sorted_internships, omitted_by_model


def _build_tailoring_summary_line(
    *,
    result: TailoredResumeOut,
    profile_dict: dict,
    experience_dicts: list[dict],
    internship_dicts: list[dict],
    skills_emphasis_dicts: list[dict],
    omitted_by_model: list[str],
    cover_letter: str,
    profile_summary: str,
) -> str:
    """One line summarizing what the draft actually contains versus the
    full profile — a plain "draft ready" line doesn't say whether the model
    kept 2 bullets or 20, dropped a whole role, or barely touched the
    summary. This is the same comparison you'd otherwise have to open the
    draft and eyeball against /profile to get.
    """
    available_bullets = sum(len(e["bullets"]) for e in profile_dict.get("experience", [])) + sum(
        len(e["bullets"]) for e in profile_dict.get("internships", [])
    )
    kept_bullets = sum(len(e["bullets"]) for e in experience_dicts) + sum(
        len(e["bullets"]) for e in internship_dicts
    )

    available_categories = profile_dict.get("skills", [])
    available_skill_count = sum(len(c["skills"]) for c in available_categories)
    emphasized_skill_count = sum(len(c["skills"]) for c in skills_emphasis_dicts)

    summary_changed = result.summary.strip() != (profile_summary or "").strip()

    parts = [
        f"bullets {kept_bullets}/{available_bullets} kept",
        f"experience {len(experience_dicts)}/{len(profile_dict.get('experience', []))}",
        f"internships {len(internship_dicts)}/{len(profile_dict.get('internships', []))}",
        f"skills {len(skills_emphasis_dicts)}/{len(available_categories)} categories "
        f"({emphasized_skill_count}/{available_skill_count} skills)",
        f"summary {'rewritten' if summary_changed else 'unchanged'}",
        f"cover letter {len(cover_letter)} chars" if cover_letter else "no cover letter",
    ]
    if omitted_by_model:
        parts.append(f"⚠ {len(omitted_by_model)} entry force-included (model omitted it): {'; '.join(omitted_by_model)}")

    return "    ↳ " + " · ".join(parts)


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
        log_progress(session, scan_run, f"Tailoring: {item_label}...", current_item=item_label, job_id=job.id)

    result = await structured_chat(
        host=config.ollama.host,
        model=config.tailoring.model,
        system=TAILORING_SYSTEM,
        user=build_tailoring_prompt(
            _profile_dict_for_main_tailoring(profile_dict),
            job.title,
            job.company_name,
            job.location_raw,
            job.description_text,
        ),
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
            log_progress(session, scan_run, f"  ✗ tailoring failed for {item_label}", job_id=job.id)
        return None

    experience_dicts, internship_dicts, omitted_by_model = _reconcile_experience_internships(result, profile_dict)
    skills_emphasis_dicts = _reconcile_skills(result.skills_emphasis, profile_dict)
    cover_letter = _strip_salutation_and_signoff(result.cover_letter)[:COVER_LETTER_MAX_LENGTH]

    # Entries in raw-description mode reach here with empty `bullets` (they
    # were excluded from the main call above) — fill them in per job now.
    for entry in experience_dicts + internship_dicts:
        if entry.get("raw_description"):
            entry["bullets"] = await _generate_bullets_from_description(
                config, entry["raw_description"], entry.get("bullet_count", 0), job.title, job.description_text
            )

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
        cover_letter=cover_letter,
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

    if draft.cover_letter.strip():
        cover_letter_pdf_path = config.resume_dir_abs_path / f"job_{job.id}_v{draft.version}_cover_letter.pdf"
        render_cover_letter_pdf(
            profile=profile,
            company_name=job.company_name,
            cover_letter=draft.cover_letter,
            output_path=cover_letter_pdf_path,
        )
        draft.cover_letter_pdf_path = str(cover_letter_pdf_path)

    job.status = "tailored"
    session.add(draft)
    session.add(job)
    session.commit()
    session.refresh(draft)
    if scan_run:
        log_progress(session, scan_run, f"  → draft v{draft.version} ready for {item_label}", job_id=job.id)
        summary_line = _build_tailoring_summary_line(
            result=result,
            profile_dict=profile_dict,
            experience_dicts=experience_dicts,
            internship_dicts=internship_dicts,
            skills_emphasis_dicts=skills_emphasis_dicts,
            omitted_by_model=omitted_by_model,
            cover_letter=cover_letter,
            profile_summary=profile.summary,
        )
        log_progress(session, scan_run, summary_line, job_id=job.id)
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

    threshold = get_score_threshold(session, config, user_id)

    drafts: list[ResumeDraft] = []
    for job in scored_jobs:
        if scan_run and is_cancelled(session, scan_run):
            log_progress(session, scan_run, "Cancelled — stopped before tailoring the remaining candidates.")
            break

        job_score = session.exec(select(JobScore).where(JobScore.job_id == job.id)).first()
        if job_score is None or job_score.score is None or job_score.score < threshold:
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
