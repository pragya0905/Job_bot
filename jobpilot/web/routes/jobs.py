import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import select

from jobpilot.auth import get_current_user
from jobpilot.config import get_config
from jobpilot.db import get_session
from jobpilot.models import ApplicationStatus, Job, JobScore, Profile, ResumeDraft, User
from jobpilot.pdf.render import render_resume_pdf
from jobpilot.pipeline.tailor import load_profile_context, tailor_one_job
from jobpilot.text_utils import split_bullet_lines, split_commas
from jobpilot.web.templates_env import templates

router = APIRouter()

VALID_APPLICATION_STATUSES = {"not_applied", "applied", "interviewing", "rejected", "offer"}


def _latest_draft(session, job_id: int) -> ResumeDraft | None:
    drafts = session.exec(
        select(ResumeDraft).where(ResumeDraft.job_id == job_id).order_by(ResumeDraft.version.desc())
    ).all()
    return drafts[0] if drafts else None


def _get_owned_job(session, job_id: int, user_id: int) -> Job | None:
    """Fetch a job only if it belongs to the requesting user — prevents one
    user from viewing or mutating another user's job/draft/application data
    by guessing IDs."""
    job = session.get(Job, job_id)
    if job is None or job.user_id != user_id:
        return None
    return job


@router.get("/jobs")
def jobs_list(
    request: Request,
    min_score: int = 0,
    status: str = "",
    applied: str = "",
    remote_only: bool = False,
    source: str = "",
    q: str = "",
    location: str = "",
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        rows = session.exec(
            select(Job, JobScore, ApplicationStatus)
            .where(Job.user_id == user.id)
            .join(JobScore, JobScore.job_id == Job.id, isouter=True)
            .join(ApplicationStatus, ApplicationStatus.job_id == Job.id, isouter=True)
        ).all()

    all_sources = sorted({job.source for job, _, _ in rows})
    all_locations = sorted({job.location_raw for job, _, _ in rows if job.location_raw})

    rows = [r for r in rows if (r[1].score if r[1] else 0) >= min_score]
    if status:
        rows = [r for r in rows if r[0].status == status]
    if applied == "not_applied":
        rows = [r for r in rows if not r[2] or r[2].status == "not_applied"]
    elif applied:
        rows = [r for r in rows if r[2] and r[2].status == applied]
    if remote_only:
        rows = [r for r in rows if r[0].is_remote]
    if source:
        rows = [r for r in rows if r[0].source == source]
    if location:
        rows = [r for r in rows if r[0].location_raw == location]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r[0].title.lower() or needle in r[0].company_name.lower()]

    rows.sort(key=lambda r: (r[1].score if r[1] else -1), reverse=True)

    return templates.TemplateResponse(
        request,
        "job_list.html",
        {
            "rows": rows,
            "min_score": min_score,
            "status": status,
            "applied": applied,
            "remote_only": remote_only,
            "source": source,
            "q": q,
            "location": location,
            "all_sources": all_sources,
            "all_locations": all_locations,
            "current_url": str(request.url),
            "application_statuses": sorted(VALID_APPLICATION_STATUSES),
        },
    )


@router.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: int, user: User = Depends(get_current_user)):
    with get_session() as session:
        job = _get_owned_job(session, job_id, user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        score = session.exec(select(JobScore).where(JobScore.job_id == job_id)).first()
        draft = _latest_draft(session, job_id)
        application = session.exec(select(ApplicationStatus).where(ApplicationStatus.job_id == job_id)).first()

    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {"job": job, "score": score, "draft": draft, "application": application},
    )


@router.post("/jobs/{job_id}/regenerate")
async def job_regenerate(job_id: int, user: User = Depends(get_current_user)):
    config = get_config()
    with get_session() as session:
        job = _get_owned_job(session, job_id, user.id)
        if job is not None:
            await tailor_one_job(session, config, job, user.id)
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/draft")
async def job_save_draft(request: Request, job_id: int, user: User = Depends(get_current_user)):
    form = await request.form()
    config = get_config()

    with get_session() as session:
        job = _get_owned_job(session, job_id, user.id)
        draft = _latest_draft(session, job_id)
        if job is None or draft is None:
            return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

        draft.summary = form.get("summary", draft.summary)
        draft.experience = _parse_experience_rows(form, prefix="exp")
        draft.internships = _parse_experience_rows(form, prefix="intern")

        skillcat_names = form.getlist("skillcat_category")
        skillcat_items = form.getlist("skillcat_items")
        draft.skills_emphasis = [
            {"category": category, "skills": split_commas(skillcat_items[i] if i < len(skillcat_items) else "")}
            for i, category in enumerate(skillcat_names)
            if category.strip()
        ]

        draft.edited_manually = True
        session.add(draft)
        session.commit()
        session.refresh(draft)

        profile, _, project_dicts, education_dicts, certification_dicts = load_profile_context(session, user.id)
        if profile is not None:
            pdf_path = Path(draft.pdf_path) if draft.pdf_path else config.resume_dir_abs_path / f"job_{job_id}_v{draft.version}.pdf"
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
            session.add(draft)
            session.commit()

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


def _parse_experience_rows(form, *, prefix: str) -> list[dict]:
    companies = form.getlist(f"{prefix}_company")
    titles = form.getlist(f"{prefix}_title")
    locations = form.getlist(f"{prefix}_location")
    dates = form.getlist(f"{prefix}_dates")
    bullets = form.getlist(f"{prefix}_bullets")
    rows = []
    for i, company in enumerate(companies):
        if not company.strip():
            continue
        rows.append(
            {
                "company": company,
                "title": titles[i] if i < len(titles) else "",
                "location": locations[i] if i < len(locations) else "",
                "dates": dates[i] if i < len(dates) else "",
                "bullets": split_bullet_lines(bullets[i] if i < len(bullets) else ""),
            }
        )
    return rows


def _resume_filename(full_name: str) -> str:
    base = re.sub(r"[^\w\s-]", "", full_name or "").strip()
    base = re.sub(r"\s+", "_", base)
    return f"{base}_Resume.pdf" if base else "Resume.pdf"


@router.get("/jobs/{job_id}/pdf")
def job_pdf(job_id: int, view: bool = False, user: User = Depends(get_current_user)):
    with get_session() as session:
        job = _get_owned_job(session, job_id, user.id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        draft = _latest_draft(session, job_id)
        profile = session.exec(select(Profile).where(Profile.user_id == user.id)).first()
    if draft is None or not draft.pdf_path or not Path(draft.pdf_path).exists():
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    filename = _resume_filename(profile.full_name if profile else "")
    disposition = "inline" if view else "attachment"
    return FileResponse(
        draft.pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.post("/jobs/{job_id}/apply")
def job_mark_applied(job_id: int, user: User = Depends(get_current_user)):
    with get_session() as session:
        job = _get_owned_job(session, job_id, user.id)
        if job is None:
            return RedirectResponse(url="/jobs", status_code=303)
        application = session.exec(select(ApplicationStatus).where(ApplicationStatus.job_id == job_id)).first()
        if application is None:
            application = ApplicationStatus(job_id=job_id)
        application.status = "applied"
        application.applied_at = datetime.utcnow()
        application.updated_at = datetime.utcnow()
        session.add(application)
        session.commit()
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/status")
async def job_set_status(request: Request, job_id: int, user: User = Depends(get_current_user)):
    """Quick inline status change from the Jobs list dropdown — same
    ApplicationStatus row as the job-detail 'Mark Applied' button, but lets
    you set any status directly instead of only 'applied'."""
    form = await request.form()
    new_status = form.get("status", "")
    return_to = form.get("return_to") or "/jobs"
    if new_status not in VALID_APPLICATION_STATUSES:
        return RedirectResponse(url=return_to, status_code=303)

    with get_session() as session:
        job = _get_owned_job(session, job_id, user.id)
        if job is not None:
            application = session.exec(select(ApplicationStatus).where(ApplicationStatus.job_id == job_id)).first()
            if application is None:
                application = ApplicationStatus(job_id=job_id)
            application.status = new_status
            if new_status == "applied" and application.applied_at is None:
                application.applied_at = datetime.utcnow()
            application.updated_at = datetime.utcnow()
            session.add(application)
            session.commit()

    return RedirectResponse(url=return_to, status_code=303)


@router.post("/jobs/delete")
async def jobs_bulk_delete(request: Request, user: User = Depends(get_current_user)):
    form = await request.form()
    job_ids = [int(v) for v in form.getlist("job_ids") if v.isdigit()]
    return_to = form.get("return_to") or "/jobs"

    with get_session() as session:
        for job_id in job_ids:
            job = _get_owned_job(session, job_id, user.id)
            if job is None:
                continue

            drafts = session.exec(select(ResumeDraft).where(ResumeDraft.job_id == job_id)).all()
            for draft in drafts:
                if draft.pdf_path:
                    pdf_file = Path(draft.pdf_path)
                    if pdf_file.exists():
                        pdf_file.unlink()
                session.delete(draft)

            for score in session.exec(select(JobScore).where(JobScore.job_id == job_id)).all():
                session.delete(score)
            for application in session.exec(select(ApplicationStatus).where(ApplicationStatus.job_id == job_id)).all():
                session.delete(application)

            session.delete(job)

        session.commit()

    return RedirectResponse(url=return_to, status_code=303)
