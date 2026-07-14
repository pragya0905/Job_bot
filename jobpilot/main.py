from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from jobpilot.auth import NotAuthenticatedError, get_or_create_session_secret
from jobpilot.db import init_db
from jobpilot.web.routes import auth, companies, dashboard, export, jobs, monitor, preferences, profile, scan


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="JobPilot", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=get_or_create_session_secret())


@app.middleware("http")
async def no_cache(request: Request, call_next):
    """Every page here is dynamic and reflects live DB state (filters,
    scan progress, application status) — never let the browser serve a
    cached copy from disk cache or the back/forward cache. Without this,
    hitting back/forward or retyping a URL with query params can show a
    stale render that looks like a broken filter or a dead feature when
    the server-side code is actually correct and current.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(NotAuthenticatedError)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedError):
    return RedirectResponse(url="/login", status_code=303)


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(profile.router)
app.include_router(companies.router)
app.include_router(preferences.router)
app.include_router(jobs.router)
app.include_router(scan.router)
app.include_router(monitor.router)
app.include_router(export.router)
