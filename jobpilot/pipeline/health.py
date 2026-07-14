from datetime import datetime

from sqlmodel import Session, select

from jobpilot.models import SourceHealth


def record_source_health(
    session: Session,
    user_id: int,
    source_key: str,
    display_name: str,
    *,
    success: bool,
    job_count: int = 0,
    error: str = "",
) -> None:
    """Upsert one row per (user, source) tracking whether a collector is
    actually working. Called after every collection attempt — success or
    failure — so a source that's silently degraded (renamed slug, new bot
    block, API shape change) shows up as unhealthy instead of just quietly
    returning fewer jobs forever with nothing surfaced but a log line that
    scrolls away.
    """
    health = session.exec(
        select(SourceHealth).where(SourceHealth.user_id == user_id, SourceHealth.source_key == source_key)
    ).first()
    if health is None:
        health = SourceHealth(user_id=user_id, source_key=source_key)

    health.display_name = display_name
    health.last_attempt_at = datetime.utcnow()
    if success:
        health.last_success_at = health.last_attempt_at
        health.last_job_count = job_count
        health.last_error = ""
        health.consecutive_failures = 0
    else:
        health.last_error = error
        health.consecutive_failures += 1

    session.add(health)
    session.commit()
