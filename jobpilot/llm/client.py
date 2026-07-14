import logging
from typing import TypeVar

import ollama
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("jobpilot.llm")

ModelT = TypeVar("ModelT", bound=BaseModel)

RETRY_REMINDER = (
    "\n\nRespond with ONLY valid JSON matching the required schema. No markdown fences, no commentary."
)


async def structured_chat(
    *,
    host: str,
    model: str,
    system: str,
    user: str,
    schema: type[ModelT],
    temperature: float = 0.0,
    max_attempts: int = 3,
    max_output_tokens: int = 2000,
    context_window: int = 8192,
) -> ModelT | None:
    """Call a local Ollama model with grammar-constrained JSON output and
    validate the response against a Pydantic schema. Retries on validation
    failure with an increasingly blunt reminder; returns None (never raises)
    after exhausting attempts so callers can mark the item `needs_review`
    instead of aborting an entire scan.

    context_window sets num_ctx explicitly. Ollama silently defaults to a
    small context window (historically 2048-4096 tokens) regardless of what
    the model itself supports — a full candidate profile (skills, multiple
    roles, internships, projects, education, certs) plus a job description
    plus our system instructions can exceed that easily. 8192 comfortably
    covers current prompt sizes; revisit if profiles grow much larger.

    think=False is the critical one: gemma4:26b is a "thinking" model — left
    on, it burns its entire token budget on chain-of-thought reasoning and
    returns a completely EMPTY structured-output field (confirmed via a
    direct diagnostic call: done_reason="length", eval_count hit the cap,
    message.content=="", all the actual generated text sitting in
    message.thinking instead). This was the real root cause behind both the
    "empty response" failures and, almost certainly, the earlier
    100k+-character "repetition loop" observed before num_predict was capped
    — that was very likely unbounded thinking, not the real answer looping.

    max_output_tokens bounds generation length as a second line of defense
    against runaway generation; with thinking disabled this should rarely be
    hit by a normal response.
    """
    client = ollama.AsyncClient(host=host)
    user_content = user

    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                format=schema.model_json_schema(),
                think=False,
                options={"temperature": temperature, "num_predict": max_output_tokens, "num_ctx": context_window},
            )
            return schema.model_validate_json(resp.message.content)
        except (ValidationError, ValueError) as exc:
            logger.warning(
                "LLM structured output validation failed (attempt %s/%s, model=%s): %s",
                attempt,
                max_attempts,
                model,
                exc,
            )
            user_content = user + RETRY_REMINDER
        except Exception as exc:  # noqa: BLE001 — network/daemon errors: don't crash the scan
            logger.warning("LLM call failed (attempt %s/%s, model=%s): %s", attempt, max_attempts, model, exc)

    return None


async def unload_model(host: str, model: str) -> None:
    """Ask Ollama to evict a model from memory immediately (keep_alive=0)
    rather than waiting out its normal idle timeout. Used when a scan is
    cancelled so a stopped scan actually frees RAM/VRAM right away instead
    of leaving a multi-GB model warm for no reason. Best-effort — a failure
    here shouldn't surface as a scan error.
    """
    client = ollama.AsyncClient(host=host)
    try:
        await client.generate(model=model, prompt="", keep_alive=0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to unload model %s: %s", model, exc)
