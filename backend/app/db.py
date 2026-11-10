"""Database access for SQLite (one machine) and PostgreSQL (a team deployment).

All writes go through write_tx(). The audit chain must stay strictly linear, so writes are
serialised: by a process-wide lock on SQLite, and by a transaction-scoped advisory lock on
PostgreSQL, which also holds across API and worker processes. Because state and audit commit
together, this lock is what makes the chain correct.

Never hold write_tx() across a network call.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_write_lock = threading.RLock()
_WRITE_ADVISORY_KEY = 7421904  # arbitrary, app-wide


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _pragmas(conn, _record):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def run_migrations(url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


def init_db(url: str, *, migrate: bool = True) -> Engine:
    """Connect, bringing the schema up to date first unless a deployment does that itself."""
    global _engine
    from . import models  # noqa: F401  (registers tables)

    if migrate:
        run_migrations(url)
    _engine = make_engine(url)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("init_db() has not been called")
    return _engine


def is_postgres() -> bool:
    return get_engine().dialect.name == "postgresql"


@contextmanager
def read_session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@contextmanager
def write_tx() -> Iterator[Session]:
    with _write_lock, Session(get_engine(), expire_on_commit=False) as session:
        session.info["write_tx"] = True
        with session.begin():
            if is_postgres():
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _WRITE_ADVISORY_KEY}
                )
            yield session
