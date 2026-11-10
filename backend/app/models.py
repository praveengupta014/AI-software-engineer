import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_in(seconds: float) -> str:
    """A timestamp in the same format as now_iso, so the two compare correctly as strings."""
    moment = datetime.now(UTC) + timedelta(seconds=seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now_iso)


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_name: Mapped[str] = mapped_column(String)
    expires_at: Mapped[str] = mapped_column(String)


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    repo: Mapped[str] = mapped_column(String)
    base_branch: Mapped[str] = mapped_column(String)
    # planning | in_progress | done | rejected | failed
    status: Mapped[str] = mapped_column(String, default="planning")
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now_iso)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)  # the GitHub issue


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON)
    stage: Mapped[str] = mapped_column(String, default="code")  # code|tests|pr|review|done
    # idle | running | awaiting_approval | blocked | done
    state: Mapped[str] = mapped_column(String, default="idle")
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)


class AgentRun(Base):
    """An agent's work, and also its place in the job queue: a run commits in the same
    transaction as the change that requested it, so work can never be lost between the two."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_queue", "status", "available_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    agent: Mapped[str] = mapped_column(String)  # planner|coder|tester|reviewer
    repo: Mapped[str] = mapped_column(String)
    requirement_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_requested_by: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[str] = mapped_column(String, default=now_iso, server_default="")
    locked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now_iso)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Proposal(Base):
    """Something an agent wants to do. Nothing takes effect until a human approves it."""

    __tablename__ = "proposals"
    __table_args__ = (Index("uq_proposals_run_id", "run_id", unique=True),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String)  # plan|code|tests|pull_request|review
    title: Mapped[str] = mapped_column(String)
    repo: Mapped[str] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    requirement_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # pending | approved | executed | failed | rejected | changes_requested
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    edited_by: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_flags: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_url: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now_iso)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ts: Mapped[str] = mapped_column(String)
    actor_type: Mapped[str] = mapped_column(String, index=True)  # agent|human|system
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String, index=True)
    subject_type: Mapped[str] = mapped_column(String)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    requirement_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String)


class WebhookDelivery(Base):
    """GitHub redelivers webhooks, so each delivery id is only ever acted on once."""

    __tablename__ = "webhook_deliveries"

    delivery_id: Mapped[str] = mapped_column(String, primary_key=True)
    event: Mapped[str] = mapped_column(String)
    received_at: Mapped[str] = mapped_column(String, default=now_iso)


class WorkerPresence(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    last_seen: Mapped[str] = mapped_column(String)


class RepoMemory(Base):
    """Guidance from people about one repository. Agent output is never stored here."""

    __tablename__ = "repo_memories"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    repo: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # convention | lesson
    applies_to: Mapped[str | None] = mapped_column(String, nullable=True)  # an agent, for lessons
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now_iso)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (Index("ix_notification_queue", "status", "available_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    channel: Mapped[str] = mapped_column(String)  # slack | teams
    proposal_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|sending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[str] = mapped_column(String, default=now_iso)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now_iso)


class TrackerLink(Base):
    """Which repository a Jira project or Linear team's tickets are built in."""

    __tablename__ = "tracker_links"
    __table_args__ = (UniqueConstraint("provider", "project_key", name="uq_tracker_links_project"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String)  # jira | linear
    project_key: Mapped[str] = mapped_column(String)
    repo: Mapped[str] = mapped_column(String)
    base_branch: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now_iso)
