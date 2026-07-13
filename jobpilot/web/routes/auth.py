from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from jobpilot.auth import hash_password, verify_password
from jobpilot.db import get_session
from jobpilot.models import Profile, User
from jobpilot.web.templates_env import templates

router = APIRouter()


@router.get("/signup")
def signup_form(request: Request):
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup")
async def signup_submit(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")

    error = None
    if not email or "@" not in email:
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != confirm_password:
        error = "Passwords don't match."

    if error is None:
        with get_session() as session:
            if session.exec(select(User).where(User.email == email)).first() is not None:
                error = "An account with that email already exists."

    if error:
        return templates.TemplateResponse(request, "signup.html", {"error": error}, status_code=400)

    with get_session() as session:
        user = User(email=email, password_hash=hash_password(password))
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(Profile(user_id=user.id))
        session.commit()
        user_id = user.id

    request.session["user_id"] = user_id
    return RedirectResponse(url="/profile", status_code=303)


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")

    with get_session() as session:
        user = session.exec(select(User).where(User.email == email)).first()

    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Incorrect email or password."}, status_code=400
        )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
