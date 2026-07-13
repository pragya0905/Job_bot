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


def init_db() -> None:
    import jobpilot.models  # noqa: F401  (register table classes)

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Session:
    return Session(get_engine())
