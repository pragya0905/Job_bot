import ollama
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from jobpilot.auth import get_current_user
from jobpilot.db import get_session
from jobpilot.config import get_config
from jobpilot.models import JobPreference, User
from jobpilot.text_utils import clean_location_entries, split_commas
from jobpilot.web.templates_env import templates

router = APIRouter()

# Suggestions for the location autocomplete — typing convenience only, not
# the matching logic itself (pipeline/filter.py's alias handling is what
# actually makes a typed city match real postings). A city missing from here
# is still fully usable — the field stays free text, this list just doesn't
# suggest it as you type. "Remote" is deliberately excluded: it's its own
# radio mode above, and always allowed automatically under "Specific
# locations or remote" regardless of what's typed here (see filter.py).
LOCATION_SUGGESTIONS = [
    "Ahmedabad", "Amritsar", "Bangalore", "Bhopal", "Bhubaneswar", "Chandigarh",
    "Chennai", "Coimbatore", "Delhi NCR", "Faridabad", "Gandhinagar", "Ghaziabad",
    "Goa", "Greater Noida", "Gurgaon", "Guwahati", "Hyderabad", "Indore", "Jaipur",
    "Kanpur", "Kochi", "Kolkata", "Lucknow", "Ludhiana", "Mumbai", "Mysuru",
    "Nagpur", "Nashik", "New Delhi", "Noida", "Patna", "Pune", "Raipur", "Ranchi",
    "Surat", "Thane", "Thiruvananthapuram", "Vadodara", "Vijayawada", "Visakhapatnam",
]


def _get_or_create_preference(session, user_id: int) -> JobPreference:
    pref = session.exec(select(JobPreference).where(JobPreference.user_id == user_id)).first()
    if pref is None:
        pref = JobPreference(user_id=user_id)
        session.add(pref)
        session.commit()
        session.refresh(pref)
    return pref


def _embedding_model_available(host: str, model: str) -> bool:
    try:
        resp = ollama.Client(host=host).list()
        return any(m.model == model or m.model == f"{model}:latest" for m in resp.models)
    except Exception:  # noqa: BLE001 — Ollama unreachable is not this page's problem to raise
        return False


@router.get("/preferences")
def preferences_form(request: Request, saved: bool = False, user: User = Depends(get_current_user)):
    with get_session() as session:
        pref = _get_or_create_preference(session, user.id)

    config = get_config()

    return templates.TemplateResponse(
        request,
        "preferences_edit.html",
        {
            "pref": pref,
            "saved": saved,
            "location_suggestions": LOCATION_SUGGESTIONS,
            "default_threshold": config.tailoring.score_threshold,
            "embedding_model": config.embedding.model,
            "embedding_model_available": _embedding_model_available(config.ollama.host, config.embedding.model),
        },
    )


@router.post("/preferences")
async def preferences_save(request: Request, user: User = Depends(get_current_user)):
    form = await request.form()

    merged_locations = clean_location_entries(form.get("preferred_locations", ""))

    try:
        threshold = int(form.get("score_threshold", ""))
    except ValueError:
        threshold = get_config().tailoring.score_threshold
    threshold = max(0, min(100, threshold))

    with get_session() as session:
        pref = _get_or_create_preference(session, user.id)
        pref.location_mode = form.get("location_mode", "specific_or_remote")
        pref.preferred_locations = merged_locations
        pref.preferred_sectors = split_commas(form.get("preferred_sectors", ""))
        pref.avoid_sectors = split_commas(form.get("avoid_sectors", ""))
        pref.score_threshold = threshold
        pref.use_semantic_scoring = form.get("use_semantic_scoring") == "true"
        session.add(pref)
        session.commit()

    return RedirectResponse(url="/preferences?saved=1", status_code=303)
