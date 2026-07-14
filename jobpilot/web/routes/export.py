import json
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlmodel import select

from jobpilot.auth import get_current_user
from jobpilot.db import get_session
from jobpilot.models import (
    ApplicationEvent,
    ApplicationStatus,
    CompanyWatch,
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
    User,
)

router = APIRouter()


@router.get("/export")
def export_data(user: User = Depends(get_current_user)):
    """Dump everything this account owns as a single JSON file — your job
    search history, profile, and preferences, structured data only (not the
    rendered PDFs, which live under data/resumes/ on disk and aren't
    included here to keep this a fast, dependency-free download).
    """
    with get_session() as session:
        profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
        profile_data = None
        if profile is not None:
            profile_data = {
                "full_name": profile.full_name,
                "email": profile.email,
                "phone": profile.phone,
                "location": profile.location,
                "links": profile.links,
                "summary": profile.summary,
                "skills": [
                    {"category": s.category, "skills": s.skills}
                    for s in session.exec(
                        select(ProfileSkillCategory).where(ProfileSkillCategory.profile_id == profile.id)
                    ).all()
                ],
                "experience": [
                    {
                        "type": e.entry_type,
                        "company": e.company,
                        "title": e.title,
                        "location": e.location,
                        "start_date": e.start_date,
                        "end_date": e.end_date,
                        "bullets": e.bullets,
                        "raw_description": e.raw_description,
                        "bullet_count": e.bullet_count,
                    }
                    for e in session.exec(
                        select(ProfileExperience).where(ProfileExperience.profile_id == profile.id)
                    ).all()
                ],
                "projects": [
                    {"name": p.name, "description": p.description, "tech": p.tech, "link": p.link}
                    for p in session.exec(select(ProfileProject).where(ProfileProject.profile_id == profile.id)).all()
                ],
                "education": [
                    {
                        "school": ed.school,
                        "degree": ed.degree,
                        "field": ed.field,
                        "start_date": ed.start_date,
                        "end_date": ed.end_date,
                        "cgpa": ed.cgpa,
                        "coursework": ed.coursework,
                    }
                    for ed in session.exec(
                        select(ProfileEducation).where(ProfileEducation.profile_id == profile.id)
                    ).all()
                ],
                "certifications": [
                    {"name": c.name, "issuer": c.issuer, "date": c.date, "credential_url": c.credential_url}
                    for c in session.exec(
                        select(ProfileCertification).where(ProfileCertification.profile_id == profile.id)
                    ).all()
                ],
            }

        preference = session.exec(select(JobPreference).where(JobPreference.user_id == user.id)).first()
        preferences_data = (
            {
                "location_mode": preference.location_mode,
                "preferred_locations": preference.preferred_locations,
                "preferred_sectors": preference.preferred_sectors,
                "avoid_sectors": preference.avoid_sectors,
                "score_threshold": preference.score_threshold,
            }
            if preference is not None
            else None
        )

        companies_data = [
            {"name": c.name, "ats_type": c.ats_type, "ats_slug": c.ats_slug, "enabled": c.enabled}
            for c in session.exec(select(CompanyWatch).where(CompanyWatch.user_id == user.id)).all()
        ]

        jobs = session.exec(select(Job).where(Job.user_id == user.id)).all()
        jobs_data = []
        for job in jobs:
            score = session.exec(select(JobScore).where(JobScore.job_id == job.id)).first()
            application = session.exec(select(ApplicationStatus).where(ApplicationStatus.job_id == job.id)).first()
            events = session.exec(
                select(ApplicationEvent).where(ApplicationEvent.job_id == job.id).order_by(ApplicationEvent.created_at)
            ).all()
            drafts = session.exec(
                select(ResumeDraft).where(ResumeDraft.job_id == job.id).order_by(ResumeDraft.version)
            ).all()

            jobs_data.append(
                {
                    "title": job.title,
                    "company": job.company_name,
                    "location": job.location_raw,
                    "salary_raw": job.salary_raw,
                    "stated_salary": job.stated_salary,
                    "estimated_comp": job.estimated_comp,
                    "estimated_comp_is_unverified": bool(job.estimated_comp),
                    "is_remote": job.is_remote,
                    "source": job.source,
                    "url": job.url,
                    "status": job.status,
                    "collected_at": job.collected_at,
                    "posted_at": job.posted_at,
                    "score": (
                        {
                            "score": score.score,
                            "rationale": score.rationale,
                            "matched_skills": score.matched_skills,
                            "missing_requirements": score.missing_requirements,
                        }
                        if score
                        else None
                    ),
                    "application": (
                        {
                            "status": application.status,
                            "applied_at": application.applied_at,
                            "updated_at": application.updated_at,
                        }
                        if application
                        else None
                    ),
                    "timeline": [{"at": e.created_at, "kind": e.kind, "text": e.text} for e in events],
                    "drafts": [
                        {
                            "version": d.version,
                            "generated_at": d.generated_at,
                            "edited_manually": d.edited_manually,
                            "summary": d.summary,
                            "experience": d.experience,
                            "internships": d.internships,
                            "skills_emphasis": d.skills_emphasis,
                            "cover_letter": d.cover_letter,
                        }
                        for d in drafts
                    ],
                }
            )

    export = {
        "exported_at": datetime.utcnow(),
        "account_email": user.email,
        "profile": profile_data,
        "preferences": preferences_data,
        "companies": companies_data,
        "jobs": jobs_data,
    }

    body = json.dumps(export, default=str, indent=2)
    filename = f"jobpilot-export-{datetime.utcnow().strftime('%Y-%m-%d')}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
