"""Read-only view of what Countersign has stored, for the Data page.

Tables must be listed here to be visible, so anything new stays private by default. Login
sessions are left out entirely, password hashes are never selected, and secrets.json is
not reachable from here at all.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, String, Text, cast, func, or_, select, text
from sqlalchemy.engine import make_url

from .config import get_settings
from .db import get_engine, is_postgres, read_session
from .models import AgentRun, AuditEvent, Proposal, RepoMemory, Requirement, Task, User

PAGE_SIZE = 25


@dataclass(frozen=True)
class Table:
    label: str
    model: type
    newest_first: Any
    secret: frozenset[str] = frozenset()  # never leaves the server
    detail_only: frozenset[str] = frozenset()  # too long for a table cell


TABLES = {
    "requirements": Table(
        "Requirements", Requirement, Requirement.created_at.desc(),
        detail_only=frozenset({"body"}),
    ),
    "tasks": Table(
        "Tasks", Task, Task.requirement_id.desc(),
        detail_only=frozenset({"description", "acceptance_criteria"}),
    ),
    "agent_runs": Table(
        "Agent runs", AgentRun, AgentRun.created_at.desc(),
        detail_only=frozenset({"feedback", "available_at", "locked_by", "heartbeat_at"}),
    ),
    "proposals": Table(
        "Proposals", Proposal, Proposal.created_at.desc(),
        detail_only=frozenset({"payload", "risk_flags"}),
    ),
    "audit_events": Table(
        "Audit events", AuditEvent, AuditEvent.seq.desc(),
        detail_only=frozenset({"data", "prev_hash", "hash"}),
    ),
    "repo_memories": Table("Memory", RepoMemory, RepoMemory.created_at.desc()),
    "users": Table(
        "People", User, User.created_at.desc(), secret=frozenset({"password_hash"}),
    ),
}


def _columns(table: Table, *, include_detail: bool) -> list[str]:
    hidden = table.secret | (frozenset() if include_detail else table.detail_only)
    return [c.name for c in table.model.__table__.columns if c.name not in hidden]


def _row(table: Table, record: Any, columns: list[str]) -> dict[str, Any]:
    return {name: getattr(record, name) for name in columns}


def _search_filter(table: Table, query: str):
    needle = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    clauses = []
    for column in table.model.__table__.columns:
        if column.name in table.secret:
            continue
        if isinstance(column.type, String | Text):
            clauses.append(column.ilike(f"%{needle}%", escape="\\"))
        elif isinstance(column.type, JSON):
            clauses.append(cast(column, String).ilike(f"%{needle}%", escape="\\"))
    return or_(*clauses)


def _storage(session: Any) -> dict[str, Any]:
    """Where data lives. A connection URL holds a password, so only safe parts are returned."""
    if is_postgres():
        url = make_url(get_engine().url)
        return {
            "kind": "postgresql",
            "path": f"{url.host}:{url.port or 5432}/{url.database}",
            "size_bytes": session.scalar(text("SELECT pg_database_size(current_database())")),
        }
    data_dir: Path = get_settings().data_dir.resolve()
    return {
        "kind": "sqlite",
        "path": str(data_dir),
        "size_bytes": sum(f.stat().st_size for f in data_dir.glob("foreman.db*")),
    }


def summary() -> dict[str, Any]:
    with read_session() as s:
        tables = [
            {"key": key, "label": t.label,
             "count": s.scalar(select(func.count()).select_from(t.model))}
            for key, t in TABLES.items()
        ]
        return {"tables": tables, "storage": _storage(s)}


def list_rows(table: Table, query: str, page: int) -> dict[str, Any]:
    columns = _columns(table, include_detail=False)
    primary_key = table.model.__table__.primary_key.columns[0].name
    statement = select(table.model)
    count = select(func.count()).select_from(table.model)
    if query:
        condition = _search_filter(table, query)
        statement = statement.where(condition)
        count = count.where(condition)
    with read_session() as s:
        records = s.scalars(
            statement.order_by(table.newest_first)
            .limit(PAGE_SIZE)
            .offset((page - 1) * PAGE_SIZE)
        ).all()
        return {
            "columns": columns,
            "primary_key": primary_key,
            "rows": [_row(table, r, columns) for r in records],
            "total": s.scalar(count),
            "page": page,
            "page_size": PAGE_SIZE,
        }


def get_row(table: Table, row_id: str) -> dict[str, Any] | None:
    key: str | int = row_id
    if table.model is AuditEvent:
        if not row_id.isdecimal():
            return None
        key = int(row_id)
    with read_session() as s:
        record = s.get(table.model, key)
        return _row(table, record, _columns(table, include_detail=True)) if record else None
