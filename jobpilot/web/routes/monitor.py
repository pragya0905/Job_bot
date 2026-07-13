from fastapi import APIRouter, Depends, Request

from jobpilot.auth import get_current_user
from jobpilot.config import get_config
from jobpilot.models import User
from jobpilot.system_info import get_cpu_memory, get_ollama_status
from jobpilot.web.templates_env import templates

router = APIRouter()


@router.get("/monitor")
def monitor_home(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "monitor.html", {})


@router.get("/monitor/status")
async def monitor_status(request: Request, user: User = Depends(get_current_user)):
    config = get_config()
    system = get_cpu_memory()
    ollama_models = await get_ollama_status(config.ollama.host)
    return templates.TemplateResponse(
        request, "monitor_status.html", {"system": system, "ollama_models": ollama_models}
    )
