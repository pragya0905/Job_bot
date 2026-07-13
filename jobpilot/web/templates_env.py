from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from jobpilot.db import get_session
from jobpilot.models import User

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _current_user_email(request: Request) -> str | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    with get_session() as session:
        user = session.get(User, user_id)
    return user.email if user else None


templates.env.globals["current_user_email"] = _current_user_email
