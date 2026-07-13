from fastapi import APIRouter, Depends, Request
from sqlmodel import func, select

from jobpilot.auth import get_current_user
from jobpilot.db import get_session
from jobpilot.models import ApplicationStatus, Job, JobScore, ResumeDraft, User
from jobpilot.web.templates_env import templates

router = APIRouter()


@router.get("/")
def dashboard(request: Request, user: User = Depends(get_current_user)):
    with get_session() as session:
        total_jobs = session.exec(
            select(func.count()).select_from(Job).where(Job.user_id == user.id)
        ).one()
        scored_jobs = session.exec(
            select(func.count())
            .select_from(JobScore)
            .join(Job, Job.id == JobScore.job_id)
            .where(Job.user_id == user.id)
        ).one()
        drafted = session.exec(
            select(func.count())
            .select_from(ResumeDraft)
            .join(Job, Job.id == ResumeDraft.job_id)
            .where(Job.user_id == user.id)
        ).one()
        applied = session.exec(
            select(func.count())
            .select_from(ApplicationStatus)
            .join(Job, Job.id == ApplicationStatus.job_id)
            .where(Job.user_id == user.id, ApplicationStatus.status == "applied")
        ).one()

        top_jobs = session.exec(
            select(Job, JobScore)
            .join(JobScore, JobScore.job_id == Job.id)
            .where(Job.user_id == user.id)
            .order_by(JobScore.score.desc())
            .limit(10)
        ).all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "total_jobs": total_jobs,
            "scored_jobs": scored_jobs,
            "drafted": drafted,
            "applied": applied,
            "top_jobs": top_jobs,
        },
    )
