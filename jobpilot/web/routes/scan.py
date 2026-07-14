from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import func, select

from jobpilot.auth import get_current_user
from jobpilot.config import get_config
from jobpilot.db import get_session
from jobpilot.models import ScanLogEntry, ScanRun, SourceHealth, User
from jobpilot.pipeline.runner import run_scan
from jobpilot.system_info import get_cpu_memory, get_ollama_status
from jobpilot.web.templates_env import templates

router = APIRouter()


@router.get("/scan")
def scan_home(request: Request, user: User = Depends(get_current_user)):
    config = get_config()
    with get_session() as session:
        runs = session.exec(
            select(ScanRun)
            .where(ScanRun.user_id == user.id)
            .order_by(ScanRun.started_at.desc())
            .limit(10)
        ).all()
        source_health = session.exec(
            select(SourceHealth)
            .where(SourceHealth.user_id == user.id)
            .order_by(SourceHealth.display_name)
        ).all()
    return templates.TemplateResponse(
        request, "scan.html", {"runs": runs, "config": config, "source_health": source_health}
    )


@router.post("/scan/run")
def scan_trigger(
    background_tasks: BackgroundTasks,
    include_linkedin: bool = Form(False),
    include_indeed: bool = Form(False),
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        scan_run = ScanRun(user_id=user.id, status="running", stage="collecting")
        session.add(scan_run)
        session.commit()
        session.refresh(scan_run)
        run_id = scan_run.id

    background_tasks.add_task(run_scan, run_id, include_linkedin=include_linkedin, include_indeed=include_indeed)
    return RedirectResponse(url=f"/scan/{run_id}", status_code=303)


@router.get("/scan/{run_id}")
def scan_detail(request: Request, run_id: int, q: str = "", user: User = Depends(get_current_user)):
    with get_session() as session:
        scan_run = session.get(ScanRun, run_id)
        if scan_run is None or scan_run.user_id != user.id:
            raise HTTPException(status_code=404, detail="Scan run not found")
    return templates.TemplateResponse(request, "scan_detail.html", {"run": scan_run, "q": q})


@router.post("/scan/{run_id}/delete")
def scan_delete(run_id: int, user: User = Depends(get_current_user)):
    with get_session() as session:
        scan_run = session.get(ScanRun, run_id)
        if scan_run is not None and scan_run.user_id == user.id and scan_run.status != "running":
            for entry in session.exec(select(ScanLogEntry).where(ScanLogEntry.scan_run_id == run_id)).all():
                session.delete(entry)
            session.delete(scan_run)
            session.commit()
    return RedirectResponse(url="/scan", status_code=303)


@router.post("/scan/delete")
async def scan_bulk_delete(request: Request, user: User = Depends(get_current_user)):
    form = await request.form()
    run_ids = [int(v) for v in form.getlist("run_ids")]
    with get_session() as session:
        runs = session.exec(
            select(ScanRun).where(ScanRun.id.in_(run_ids), ScanRun.user_id == user.id, ScanRun.status != "running")
        ).all()
        for run in runs:
            for entry in session.exec(select(ScanLogEntry).where(ScanLogEntry.scan_run_id == run.id)).all():
                session.delete(entry)
            session.delete(run)
        session.commit()
    return RedirectResponse(url="/scan", status_code=303)


@router.post("/scan/{run_id}/cancel")
def scan_cancel(run_id: int, user: User = Depends(get_current_user)):
    with get_session() as session:
        scan_run = session.get(ScanRun, run_id)
        if scan_run is not None and scan_run.user_id == user.id and scan_run.status == "running":
            scan_run.cancel_requested = True
            session.add(scan_run)
            session.commit()
    return RedirectResponse(url=f"/scan/{run_id}", status_code=303)


@router.get("/scan/{run_id}/status")
async def scan_status(request: Request, run_id: int, q: str = "", user: User = Depends(get_current_user)):
    with get_session() as session:
        scan_run = session.get(ScanRun, run_id)
        if scan_run is None or scan_run.user_id != user.id:
            raise HTTPException(status_code=404, detail="Scan run not found")

        log_query = select(ScanLogEntry).where(ScanLogEntry.scan_run_id == run_id)
        if q:
            log_query = log_query.where(ScanLogEntry.message.ilike(f"%{q}%"))
        log_entries = session.exec(log_query.order_by(ScanLogEntry.id)).all()
        total_log_count = session.exec(
            select(func.count()).select_from(ScanLogEntry).where(ScanLogEntry.scan_run_id == run_id)
        ).one()

    system = None
    ollama_models = []
    if scan_run.status == "running":
        config = get_config()
        system = get_cpu_memory()
        ollama_models = await get_ollama_status(config.ollama.host)

    return templates.TemplateResponse(
        request,
        "scan_progress.html",
        {
            "run": scan_run,
            "system": system,
            "ollama_models": ollama_models,
            "log_entries": log_entries,
            "total_log_count": total_log_count,
            "q": q,
        },
    )
