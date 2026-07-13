from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from jobpilot.auth import get_current_user
from jobpilot.db import get_session
from jobpilot.models import (
    Profile,
    ProfileCertification,
    ProfileEducation,
    ProfileExperience,
    ProfileProject,
    ProfileSkillCategory,
    User,
)
from jobpilot.text_utils import split_bullet_lines, split_commas
from jobpilot.web.templates_env import templates

router = APIRouter()


def _get_or_create_profile(session, user_id: int) -> Profile:
    profile = session.exec(select(Profile).where(Profile.user_id == user_id)).first()
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


@router.get("/profile")
def profile_form(request: Request, saved: bool = False, user: User = Depends(get_current_user)):
    with get_session() as session:
        profile = _get_or_create_profile(session, user.id)
        all_experience = session.exec(
            select(ProfileExperience)
            .where(ProfileExperience.profile_id == profile.id)
            .order_by(ProfileExperience.order_index)
        ).all()
        experience = [e for e in all_experience if e.entry_type != "internship"]
        internships = [e for e in all_experience if e.entry_type == "internship"]
        projects = session.exec(
            select(ProfileProject)
            .where(ProfileProject.profile_id == profile.id)
            .order_by(ProfileProject.order_index)
        ).all()
        education = session.exec(
            select(ProfileEducation)
            .where(ProfileEducation.profile_id == profile.id)
            .order_by(ProfileEducation.order_index)
        ).all()
        certifications = session.exec(
            select(ProfileCertification)
            .where(ProfileCertification.profile_id == profile.id)
            .order_by(ProfileCertification.order_index)
        ).all()
        skill_categories = session.exec(
            select(ProfileSkillCategory)
            .where(ProfileSkillCategory.profile_id == profile.id)
            .order_by(ProfileSkillCategory.order_index)
        ).all()
    return templates.TemplateResponse(
        request,
        "profile_edit.html",
        {
            "profile": profile,
            "experience": experience,
            "internships": internships,
            "projects": projects,
            "education": education,
            "certifications": certifications,
            "skill_categories": skill_categories,
            "saved": saved,
        },
    )


@router.post("/profile")
async def profile_save(request: Request, user: User = Depends(get_current_user)):
    form = await request.form()

    with get_session() as session:
        profile = _get_or_create_profile(session, user.id)
        profile.full_name = form.get("full_name", "")
        profile.email = form.get("email", "")
        profile.phone = form.get("phone", "")
        profile.location = form.get("location", "")
        profile.summary = form.get("summary", "")
        profile.links = _split_lines(form.get("links", ""))
        profile.updated_at = datetime.utcnow()
        session.add(profile)

        # Replace child rows wholesale on every save — simplest correct approach
        # for a single-user form with no concurrent editors.
        for model in (
            ProfileExperience,
            ProfileProject,
            ProfileEducation,
            ProfileCertification,
            ProfileSkillCategory,
        ):
            for row in session.exec(select(model).where(model.profile_id == profile.id)).all():
                session.delete(row)
        session.commit()

        _save_experience_rows(session, profile.id, form, prefix="exp", entry_type="experience")
        _save_experience_rows(session, profile.id, form, prefix="intern", entry_type="internship")

        proj_names = form.getlist("proj_name")
        proj_descs = form.getlist("proj_description")
        proj_techs = form.getlist("proj_tech")
        proj_links = form.getlist("proj_link")
        for i, name in enumerate(proj_names):
            if not name.strip():
                continue
            session.add(
                ProfileProject(
                    profile_id=profile.id,
                    name=name,
                    description=proj_descs[i] if i < len(proj_descs) else "",
                    tech=split_commas(proj_techs[i] if i < len(proj_techs) else ""),
                    link=proj_links[i] if i < len(proj_links) else "",
                    order_index=i,
                )
            )

        edu_schools = form.getlist("edu_school")
        edu_degrees = form.getlist("edu_degree")
        edu_fields = form.getlist("edu_field")
        edu_starts = form.getlist("edu_start_date")
        edu_ends = form.getlist("edu_end_date")
        for i, school in enumerate(edu_schools):
            if not school.strip():
                continue
            session.add(
                ProfileEducation(
                    profile_id=profile.id,
                    school=school,
                    degree=edu_degrees[i] if i < len(edu_degrees) else "",
                    field=edu_fields[i] if i < len(edu_fields) else "",
                    start_date=edu_starts[i] if i < len(edu_starts) else "",
                    end_date=edu_ends[i] if i < len(edu_ends) else "",
                    order_index=i,
                )
            )

        cert_names = form.getlist("cert_name")
        cert_issuers = form.getlist("cert_issuer")
        cert_dates = form.getlist("cert_date")
        cert_urls = form.getlist("cert_url")
        for i, name in enumerate(cert_names):
            if not name.strip():
                continue
            session.add(
                ProfileCertification(
                    profile_id=profile.id,
                    name=name,
                    issuer=cert_issuers[i] if i < len(cert_issuers) else "",
                    date=cert_dates[i] if i < len(cert_dates) else "",
                    credential_url=cert_urls[i] if i < len(cert_urls) else "",
                    order_index=i,
                )
            )

        skillcat_names = form.getlist("skillcat_category")
        skillcat_items = form.getlist("skillcat_items")
        for i, category in enumerate(skillcat_names):
            if not category.strip():
                continue
            session.add(
                ProfileSkillCategory(
                    profile_id=profile.id,
                    category=category,
                    skills=split_commas(skillcat_items[i] if i < len(skillcat_items) else ""),
                    order_index=i,
                )
            )

        session.commit()

    return RedirectResponse(url="/profile?saved=1", status_code=303)


def _save_experience_rows(session, profile_id: int, form, *, prefix: str, entry_type: str) -> None:
    companies = form.getlist(f"{prefix}_company")
    titles = form.getlist(f"{prefix}_title")
    locations = form.getlist(f"{prefix}_location")
    starts = form.getlist(f"{prefix}_start_date")
    ends = form.getlist(f"{prefix}_end_date")
    bullets = form.getlist(f"{prefix}_bullets")
    for i, company in enumerate(companies):
        if not company.strip():
            continue
        session.add(
            ProfileExperience(
                profile_id=profile_id,
                entry_type=entry_type,
                company=company,
                title=titles[i] if i < len(titles) else "",
                location=locations[i] if i < len(locations) else "",
                start_date=starts[i] if i < len(starts) else "",
                end_date=ends[i] if i < len(ends) else "",
                order_index=i,
                bullets=split_bullet_lines(bullets[i] if i < len(bullets) else ""),
            )
        )


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
