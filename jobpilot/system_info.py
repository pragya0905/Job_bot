import psutil
import ollama


def get_cpu_memory() -> dict:
    # interval=None is non-blocking (compares against the last call) rather
    # than sleeping — important since this gets polled from an async route.
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_total_gb": round(mem.total / (1024**3), 1),
    }


async def get_ollama_status(host: str) -> list[dict]:
    client = ollama.AsyncClient(host=host)
    try:
        resp = await client.ps()
    except Exception:
        return []
    return [
        {
            "name": m.model,
            "size_gb": round(m.size / (1024**3), 2),
            "vram_gb": round(m.size_vram / (1024**3), 2) if m.size_vram else 0,
            "context_length": m.context_length,
            "expires_at": m.expires_at,
        }
        for m in resp.models
    ]
