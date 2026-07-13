from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from jobpilot.auth import get_current_user
from jobpilot.db import get_session
from jobpilot.models import CompanyWatch, User
from jobpilot.web.templates_env import templates

router = APIRouter()


@router.get("/companies")
def companies_list(request: Request, user: User = Depends(get_current_user)):
    with get_session() as session:
        companies = session.exec(
            select(CompanyWatch).where(CompanyWatch.user_id == user.id).order_by(CompanyWatch.name)
        ).all()
    return templates.TemplateResponse(request, "companies.html", {"companies": companies})


@router.post("/companies")
def companies_add(
    name: str = Form(...),
    ats_type: str = Form(...),
    ats_slug: str = Form(...),
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        session.add(CompanyWatch(user_id=user.id, name=name, ats_type=ats_type, ats_slug=ats_slug, enabled=True))
        session.commit()
    return RedirectResponse(url="/companies", status_code=303)


@router.post("/companies/{company_id}/toggle")
def companies_toggle(company_id: int, user: User = Depends(get_current_user)):
    with get_session() as session:
        company = session.get(CompanyWatch, company_id)
        if company and company.user_id == user.id:
            company.enabled = not company.enabled
            session.add(company)
            session.commit()
    return RedirectResponse(url="/companies", status_code=303)


@router.post("/companies/{company_id}/delete")
def companies_delete(company_id: int, user: User = Depends(get_current_user)):
    with get_session() as session:
        company = session.get(CompanyWatch, company_id)
        if company and company.user_id == user.id:
            session.delete(company)
            session.commit()
    return RedirectResponse(url="/companies", status_code=303)
