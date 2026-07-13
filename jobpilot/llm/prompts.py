import json

from jobpilot.models import (
    Profile,
    ProfileCertification,
    ProfileEducation,
    ProfileExperience,
    ProfileProject,
    ProfileSkillCategory,
)

SCORING_SYSTEM = """You are an expert technical recruiter evaluating fit between a candidate \
and a job description for the candidate's own benefit — help them decide if this job is worth \
their time, not just whether keywords overlap. Weigh actual experience depth, seniority match, \
and domain relevance. If the role says "remote" but is scoped to a specific country/region the \
candidate isn't in, factor that into the score and say so in the rationale. If the candidate has \
stated sector preferences below, treat them as a soft signal, not a hard requirement: nudge the \
score up a little for a good sector match and down a little for a sector they want to avoid, but \
a strong role/skills fit should still outscore a weak one even in a preferred sector. Mention the \
sector fit in the rationale only when it materially affected the score. Score 0-100. Keep the \
rationale to 2-3 concise sentences, not an essay."""

TAILORING_SYSTEM = """You are an expert resume writer helping a candidate tailor their resume to a \
specific job description. You may ONLY reorder and re-emphasize content that already exists in the \
candidate's profile below. Never invent employers, titles, dates, metrics, or skills that are not \
present in the profile. Rewrite the summary to speak directly to what this job asks for. \
\
EVERY experience entry and EVERY internship entry listed in the candidate profile below MUST appear \
in your output — the candidate wants their full work history shown for every job, not a curated \
subset. Never omit an entire role or internship, no matter how junior or seemingly irrelevant it \
looks for this job. Your only job at the entry level is to decide the ORDER of entries and which \
BULLETS within each entry to include/reorder — never whether an entire entry appears at all. \
\
For each role's bullets (and each internship's bullets), copy each bullet EXACTLY character-for- \
character as it appears in the profile — do not reword, paraphrase, or fix wording even slightly — \
you may choose which bullets to include (you may omit a bullet, but an entry must keep at least one) \
and reorder them to foreground the most relevant achievements first. Any change to a bullet's \
wording, however small, is treated as an error. The profile below has separate "experience" and \
"internships" lists — output your tailored "experience" entries and "internships" entries in those \
same two separate lists, matching each entry to whichever list it came from, and every entry from \
both source lists must be represented exactly once across your output. Never move an internship \
into "experience" and never duplicate the same entry into both lists. For skills, output category \
names EXACTLY as they appear in the profile's skill list — never invent a new category name or \
description, never add commentary into a category name. Within each category you may select and \
reorder skills to foreground what's most relevant to this job, but every skill you output under a \
category must already be listed under that exact category in the profile."""


def profile_to_dict(
    profile: Profile,
    experience: list[ProfileExperience],
    projects: list[ProfileProject],
    education: list[ProfileEducation],
    certifications: list[ProfileCertification],
    skill_categories: list[ProfileSkillCategory],
) -> dict:
    return {
        "full_name": profile.full_name,
        "location": profile.location,
        "summary": profile.summary,
        "skills": [{"category": s.category, "skills": s.skills} for s in skill_categories],
        "experience": [
            {
                "company": e.company,
                "title": e.title,
                "location": e.location,
                "dates": f"{e.start_date} - {e.end_date}",
                "bullets": e.bullets,
            }
            for e in experience
            if e.entry_type != "internship"
        ],
        "internships": [
            {
                "company": e.company,
                "title": e.title,
                "location": e.location,
                "dates": f"{e.start_date} - {e.end_date}",
                "bullets": e.bullets,
            }
            for e in experience
            if e.entry_type == "internship"
        ],
        "projects": [
            {"name": p.name, "description": p.description, "tech": p.tech}
            for p in projects
        ],
        "education": [
            {"school": e.school, "degree": e.degree, "field": e.field}
            for e in education
        ],
        "certifications": [
            {"name": c.name, "issuer": c.issuer, "date": c.date}
            for c in certifications
        ],
    }


def build_scoring_prompt(
    profile_dict: dict,
    job_title: str,
    company_name: str,
    location: str,
    description: str,
    preferred_sectors: list[str] | None = None,
    avoid_sectors: list[str] | None = None,
) -> str:
    preference_block = ""
    if preferred_sectors or avoid_sectors:
        parts = []
        if preferred_sectors:
            parts.append(f"Prioritize sectors: {', '.join(preferred_sectors)}")
        if avoid_sectors:
            parts.append(f"Deprioritize sectors: {', '.join(avoid_sectors)}")
        preference_block = "\n\nCANDIDATE PREFERENCES:\n" + "\n".join(parts)

    return (
        f"CANDIDATE PROFILE:\n{json.dumps(profile_dict, indent=2)}"
        f"{preference_block}\n\n"
        f"JOB:\nTitle: {job_title}\nCompany: {company_name}\nLocation: {location}\n\n"
        f"DESCRIPTION:\n{description[:6000]}"
    )


def build_tailoring_prompt(profile_dict: dict, job_title: str, company_name: str, location: str, description: str) -> str:
    return (
        f"CANDIDATE PROFILE (only source of truth — do not add anything not in here):\n"
        f"{json.dumps(profile_dict, indent=2)}\n\n"
        f"JOB:\nTitle: {job_title}\nCompany: {company_name}\nLocation: {location}\n\n"
        f"DESCRIPTION:\n{description[:6000]}"
    )
