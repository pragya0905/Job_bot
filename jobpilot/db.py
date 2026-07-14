import json
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from jobpilot.config import get_config

_engine = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        config = get_config()
        config.database_abs_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{config.database_abs_path}")
    return _engine


def _migrate_add_columns() -> None:
    """create_all only creates missing tables, never alters existing ones.
    Columns added to models after the DB file already exists need a manual
    ALTER TABLE — there's no Alembic in this project, so this stays a small
    hand-rolled list rather than pulling in a migration framework for a
    single-user-editable SQLite file.
    """
    additions = {
        "scanrun": [("cancel_requested", "BOOLEAN DEFAULT 0")],
        "jobpreference": [
            ("score_threshold", "INTEGER DEFAULT 75"),
            ("use_semantic_scoring", "BOOLEAN DEFAULT 0"),
        ],
        "resumedraft": [("cover_letter", "TEXT DEFAULT ''"), ("cover_letter_pdf_path", "TEXT DEFAULT ''")],
        "job": [
            ("last_seen_at", "TIMESTAMP"),
            ("salary_raw", "TEXT DEFAULT ''"),
            ("stated_salary", "TEXT"),
            ("estimated_comp", "TEXT"),
            ("tailoring_in_progress", "BOOLEAN DEFAULT 0"),
        ],
        "jobscore": [("semantic_score", "INTEGER")],
        "profileeducation": [("cgpa", "TEXT DEFAULT ''"), ("coursework", "JSON DEFAULT '[]'")],
        "profileexperience": [("raw_description", "TEXT DEFAULT ''"), ("bullet_count", "INTEGER DEFAULT 0")],
    }
    engine = get_engine()
    with engine.connect() as conn:
        added: set[tuple[str, str]] = set()
        for table, columns in additions.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for column_name, ddl_type in columns:
                if column_name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column_name} {ddl_type}")
                    added.add((table, column_name))
        if ("job", "last_seen_at") in added:
            # New column starts NULL on every existing row — backfill from
            # collected_at rather than "now" so pre-existing jobs don't all
            # look freshly-seen (and therefore never stale) on day one.
            conn.exec_driver_sql("UPDATE job SET last_seen_at = collected_at WHERE last_seen_at IS NULL")
        conn.commit()


def _migrate_backfill_scan_logs() -> None:
    """ScanRun used to carry its own log as a capped log_lines JSON array
    before ScanLogEntry became a proper permanent, per-job-taggable table.
    This copies any pre-existing scan history over exactly once, so old
    scans' logs aren't silently lost when this ships — the log_lines column
    itself is left in place on disk afterward (harmless, just unmapped)
    rather than risking a DROP COLUMN on a live SQLite file.
    """
    engine = get_engine()
    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(scanrun)")}
        if "log_lines" not in columns:
            return  # fresh install — this column (and thus the old format) never existed

        already_backfilled = conn.exec_driver_sql("SELECT COUNT(*) FROM scanlogentry").scalar()
        if already_backfilled:
            return  # only ever run once, right after scanlogentry first appears

        rows = conn.exec_driver_sql("SELECT id, log_lines FROM scanrun WHERE log_lines IS NOT NULL").fetchall()
        for scan_run_id, log_lines_json in rows:
            if not log_lines_json:
                continue
            for line in json.loads(log_lines_json):
                conn.exec_driver_sql(
                    "INSERT INTO scanlogentry (scan_run_id, job_id, created_at, message) VALUES (?, NULL, ?, ?)",
                    (scan_run_id, datetime.utcnow().isoformat(sep=" "), line),
                )
        conn.commit()


def _reset_stale_tailoring_flags() -> None:
    """tailoring_in_progress is only ever meaningful for the lifetime of the
    background task that set it — a server restart mid-generation (crash,
    manual restart, --reload) kills that task without a chance to clear the
    flag, which would otherwise leave the job stuck showing "Generating..."
    forever. Safe to run unconditionally on every startup.
    """
    engine = get_engine()
    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(job)")}
        if "tailoring_in_progress" in columns:
            conn.exec_driver_sql("UPDATE job SET tailoring_in_progress = 0 WHERE tailoring_in_progress = 1")
            conn.commit()


def init_db() -> None:
    import jobpilot.models  # noqa: F401  (register table classes)

    SQLModel.metadata.create_all(get_engine())
    _migrate_add_columns()
    _migrate_backfill_scan_logs()
    _reset_stale_tailoring_flags()


def get_session() -> Session:
    return Session(get_engine())
