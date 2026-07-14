import logging
import math

import ollama

logger = logging.getLogger("jobpilot.embeddings")


async def embed_text(host: str, model: str, text: str) -> list[float] | None:
    """Embed a piece of text with a local Ollama embedding model. Returns
    None (never raises) if the call fails — most commonly because the
    embedding model (e.g. nomic-embed-text) hasn't been pulled, which is an
    opt-in feature dependency, not something that should ever crash a scan.
    """
    client = ollama.AsyncClient(host=host)
    try:
        resp = await client.embed(model=model, input=text[:8000])
        return list(resp.embeddings[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding call failed (model=%s): %s", model, exc)
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def profile_text_for_embedding(profile_dict: dict) -> str:
    """Flatten the structured profile into one text blob suitable for
    embedding — summary, skills, and every bullet across experience,
    internships, and projects, so the vector captures the full breadth of
    the candidate's background rather than just the summary line."""
    parts = [profile_dict.get("summary", "")]
    for cat in profile_dict.get("skills", []):
        parts.append(", ".join(cat.get("skills", [])))
    for entry in profile_dict.get("experience", []) + profile_dict.get("internships", []):
        parts.append(entry.get("title", ""))
        parts.extend(entry.get("bullets", []))
    for project in profile_dict.get("projects", []):
        parts.append(project.get("description", ""))
    return "\n".join(p for p in parts if p)
