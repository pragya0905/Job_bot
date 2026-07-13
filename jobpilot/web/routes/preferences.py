from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from jobpilot.auth import get_current_user
from jobpilot.db import get_session
from jobpilot.models import JobPreference, User
from jobpilot.text_utils import split_commas
from jobpilot.web.templates_env import templates

router = APIRouter()

# Curated rather than pulled from the user's own collected jobs: raw job
# postings' location strings are messy/compound (e.g. "New York, San
# Francisco, Seattle, or Remote (US/Canada)"), and short canonical city
# names are what the substring-match location filter actually needs anyway.
COMMON_LOCATIONS = [
    "Remote",
    "Hyderabad",
    "Bangalore",
    "Mumbai",
    "Pune",
    "Delhi NCR",
    "Gurgaon",
    "Noida",
    "Chennai",
    "Kolkata",
]


def _get_or_create_preference(session, user_id: int) -> JobPreference:
    pref = session.exec(select(JobPreference).where(JobPreference.user_id == user_id)).first()
    if pref is None:
        pref = JobPreference(user_id=user_id)
        session.add(pref)
        session.commit()
        session.refresh(pref)
    return pref


@router.get("/preferences")
def preferences_form(request: Request, saved: bool = False, user: User = Depends(get_current_user)):
    with get_session() as session:
        pref = _get_or_create_preference(session, user.id)

    # Anything already saved that isn't in the curated list shows up in the
    # "other" free-text field instead of silently disappearing.
    other_locations = [loc for loc in pref.preferred_locations if loc not in COMMON_LOCATIONS]

    return templates.TemplateResponse(
        request,
        "preferences_edit.html",
        {
            "pref": pref,
            "saved": saved,
            "location_options": COMMON_LOCATIONS,
            "other_locations": ", ".join(other_locations),
        },
    )


@router.post("/preferences")
async def preferences_save(request: Request, user: User = Depends(get_current_user)):
    form = await request.form()

    selected_locations = form.getlist("preferred_locations")
    other_locations = split_commas(form.get("preferred_locations_other", ""))
    merged_locations = list(dict.fromkeys(selected_locations + other_locations))  # dedupe, keep order

    with get_session() as session:
        pref = _get_or_create_preference(session, user.id)
        pref.location_mode = form.get("location_mode", "specific_or_remote")
        pref.preferred_locations = merged_locations
        pref.preferred_sectors = split_commas(form.get("preferred_sectors", ""))
        pref.avoid_sectors = split_commas(form.get("avoid_sectors", ""))
        session.add(pref)
        session.commit()

    return RedirectResponse(url="/preferences?saved=1", status_code=303)
