import secrets
from pathlib import Path

import bcrypt
from fastapi import Request
from sqlmodel import select

from jobpilot.db import get_session
from jobpilot.models import User

SECRET_KEY_PATH = Path(__file__).resolve().parent.parent / "data" / ".session_secret"


class NotAuthenticatedError(Exception):
    """Raised by get_current_user when no valid session is present.

    Caught by a FastAPI exception handler (registered in main.py) that
    redirects to /login — keeps every protected route handler free of
    manual auth-check boilerplate.
    """


def get_or_create_session_secret() -> str:
    """A stable secret key for signing session cookies, generated once and
    persisted locally so sessions survive server restarts. Never committed
    (lives under the already-gitignored data/ directory).
    """
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(secret)
    return secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def get_current_user(request: Request) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise NotAuthenticatedError()

    with get_session() as session:
        user = session.get(User, user_id)
    if user is None:
        raise NotAuthenticatedError()
    return user
